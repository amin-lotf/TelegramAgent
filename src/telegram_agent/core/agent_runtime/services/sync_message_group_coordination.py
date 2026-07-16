from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from uuid import UUID

from pydantic import ValidationError

from telegram_agent.core.agent_runtime.clients.llm_gateway import LlmGatewayClient
from telegram_agent.core.agent_runtime.common.results import (
    ConversationCoordinationResult,
    MessageCoordinationResult,
)
from telegram_agent.core.agent_runtime.common.models import (
    CoordinatorDecision,
    CoordinatorMessageView,
)
from telegram_agent.core.agent_runtime.common.settings import Settings, settings
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    CoordinatorDecisionKind,
)
from telegram_agent.core.agent_runtime.db.models.runtime import RuntimeMessage
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
from telegram_agent.core.agent_runtime.prompts.message_grouping import (
    build_message_grouping_prompts,
)
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)
from telegram_agent.core.common.utils import utcnow

logger = logging.getLogger(__name__)


class SyncMessageGroupCoordinationService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyAgentRuntimeUnitOfWork],
        ],
        llm_gateway_client: LlmGatewayClient,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._llm_gateway_client = llm_gateway_client
        self._settings = settings

    @classmethod
    def from_settings(
        cls,
        *,
        llm_gateway_client: LlmGatewayClient | None = None,
    ) -> "SyncMessageGroupCoordinationService":
        if llm_gateway_client is None:
            if settings.llm_gateway_service_token is None:
                raise RuntimeError("LLM_GATEWAY_SERVICE_TOKEN must be configured")
            llm_gateway_client = LlmGatewayClient(
                base_url=settings.llm_gateway_base_url,
                token=settings.llm_gateway_service_token,
                timeout_seconds=settings.llm_gateway_request_timeout_seconds,
            )
        return cls(
            uow_factory=sync_agent_runtime_uow_factory,
            llm_gateway_client=llm_gateway_client,
            settings=settings,
        )

    def process_conversation(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
    ) -> ConversationCoordinationResult:
        lease_timeout = timedelta(
            seconds=self._settings.coordination_claim_lease_seconds
        )

        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                logger.info(
                    "Skipping conversation without a valid claim token",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                    },
                )
                return ConversationCoordinationResult(
                    chat_id=chat_id,
                    processed=0,
                    results=(),
                )

            pending_messages = uow.messages.list_pending_for_chat(
                chat_id=chat_id,
                limit=self._settings.coordination_message_batch_size,
            )
            message_ids = [message.id for message in pending_messages]

        results: list[MessageCoordinationResult] = []
        try:
            for runtime_message_id in message_ids:
                with self._uow_factory() as uow:
                    renewed = uow.conversation_claims.renew(
                        chat_id=chat_id,
                        claim_token=claim_token,
                        lease_timeout=lease_timeout,
                    )
                    if renewed is None:
                        logger.info(
                            "Stopping coordination; claim token no longer valid",
                            extra={
                                "chat_id": chat_id,
                                "claim_token": str(claim_token),
                            },
                        )
                        return ConversationCoordinationResult(
                            chat_id=chat_id,
                            processed=len(results),
                            results=tuple(results),
                        )

                result = self._coordinate_single_message(
                    chat_id=chat_id,
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                )
                if result is None:
                    break
                results.append(result)
        finally:
            with self._uow_factory() as uow:
                uow.conversation_claims.release(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    available_at=utcnow(),
                )

        return ConversationCoordinationResult(
            chat_id=chat_id,
            processed=len(results),
            results=tuple(results),
        )

    def _coordinate_single_message(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageCoordinationResult | None:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                return None

            message = uow.messages.get_by_id(runtime_message_id)
            if message is None:
                return None
            if message.chat_id != chat_id:
                return None
            if message.coordination_status != CoordinationStatus.PENDING:
                return None

            earlier_pending = uow.messages.list_pending_for_chat(
                chat_id=chat_id,
                limit=1,
            )
            if earlier_pending and earlier_pending[0].id != message.id:
                return None

            recent = uow.messages.list_recent_before(
                chat_id=chat_id,
                before_message_id=message.message_id,
                limit=self._settings.coordination_recent_window_size,
            )
            current_view = self._to_view(message)
            recent_views = tuple(self._to_view(item) for item in recent)
            allowed_group_numbers = {
                view.group_number
                for view in recent_views
                if view.group_number is not None
            }

        try:
            prompts = build_message_grouping_prompts(
                current=current_view,
                recent_window=recent_views,
            )
            generation = self._llm_gateway_client.coordinate_message_group(
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
            )
            try:
                decision = CoordinatorDecision.model_validate(generation.output)
            except ValidationError as exc:
                raise RetryableAgentRuntimeCoordinationError(
                    "LLM gateway returned an invalid coordination decision"
                ) from exc
            return self._apply_decision(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                decision=decision,
                allowed_group_numbers=allowed_group_numbers,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            )
        except PermanentAgentRuntimeCoordinationError as exc:
            self._record_permanent_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                error=exc,
            )
            return None
        except RetryableAgentRuntimeCoordinationError as exc:
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error=exc,
            )
            return None
        except Exception as exc:
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error=exc,
            )
            logger.exception(
                "Unexpected coordination failure",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                },
            )
            return None

    def _apply_decision(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        decision: CoordinatorDecision,
        allowed_group_numbers: set[int],
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageCoordinationResult:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                raise RetryableAgentRuntimeCoordinationError(
                    "Claim token is no longer valid"
                )

            message = uow.messages.get_by_id(runtime_message_id)
            if message is None or message.coordination_status != CoordinationStatus.PENDING:
                raise RetryableAgentRuntimeCoordinationError(
                    "Message is no longer pending for coordination"
                )

            if decision.kind == CoordinatorDecisionKind.NEW:
                group = uow.groups.allocate_next(chat_id=chat_id)
                updated = uow.messages.mark_grouped(
                    runtime_message_id=runtime_message_id,
                    group_id=group.id,
                )
                if updated is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark message as grouped"
                    )
                published = uow.outbox_events.mark_published_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                )
                if published is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark outbox published under active claim"
                    )
                return MessageCoordinationResult(
                    runtime_message_id=runtime_message_id,
                    status=CoordinationStatus.GROUPED.value,
                    group_id=group.id,
                    group_number=group.group_number,
                )

            if decision.kind == CoordinatorDecisionKind.EXISTING:
                if (
                    decision.group_number is None
                    or decision.group_number not in allowed_group_numbers
                ):
                    return self._apply_vague(
                        uow=uow,
                        runtime_message_id=runtime_message_id,
                        claim_token=claim_token,
                    )

                group = uow.groups.get_by_chat_and_number(
                    chat_id=chat_id,
                    group_number=decision.group_number,
                )
                if group is None:
                    return self._apply_vague(
                        uow=uow,
                        runtime_message_id=runtime_message_id,
                        claim_token=claim_token,
                    )

                updated = uow.messages.mark_grouped(
                    runtime_message_id=runtime_message_id,
                    group_id=group.id,
                )
                if updated is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark message as grouped"
                    )
                published = uow.outbox_events.mark_published_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                )
                if published is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark outbox published under active claim"
                    )
                return MessageCoordinationResult(
                    runtime_message_id=runtime_message_id,
                    status=CoordinationStatus.GROUPED.value,
                    group_id=group.id,
                    group_number=group.group_number,
                )

            if decision.kind == CoordinatorDecisionKind.VAGUE:
                return self._apply_vague(
                    uow=uow,
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                )

            raise PermanentAgentRuntimeCoordinationError(
                f"Unsupported coordinator decision kind: {decision.kind}"
            )

    def _apply_vague(
        self,
        *,
        uow: SyncSqlAlchemyAgentRuntimeUnitOfWork,
        runtime_message_id: UUID,
        claim_token: UUID,
    ) -> MessageCoordinationResult:
        updated = uow.messages.mark_vague(runtime_message_id=runtime_message_id)
        if updated is None:
            raise RetryableAgentRuntimeCoordinationError(
                "Failed to mark message as vague"
            )
        published = uow.outbox_events.mark_published_for_message(
            runtime_message_id=runtime_message_id,
            claim_token=claim_token,
        )
        if published is None:
            raise RetryableAgentRuntimeCoordinationError(
                "Failed to mark outbox published under active claim"
            )
        return MessageCoordinationResult(
            runtime_message_id=runtime_message_id,
            status=CoordinationStatus.VAGUE.value,
            group_id=None,
            group_number=None,
        )

    def _record_retryable_failure(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        error: Exception,
    ) -> None:
        with self._uow_factory() as uow:
            event = uow.outbox_events.get_by_runtime_message_id(runtime_message_id)
            attempt_count = 0 if event is None else event.attempt_count
            next_available_at = utcnow() + self._retry_delay(attempt_count)
            updated = uow.outbox_events.record_failure_for_message(
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error_message=str(error),
                next_available_at=next_available_at,
            )
        if updated is None:
            logger.info(
                "Skipped retryable failure recording; claim token no longer active",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "claim_token": str(claim_token),
                },
            )
            return
        logger.warning(
            "Retryable coordination failure",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "attempt_count": updated.attempt_count,
                "next_available_at": next_available_at.isoformat(),
                "error": str(error),
            },
        )

    def _record_permanent_failure(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
        error: Exception,
    ) -> None:
        """Atomically mark message vague and outbox FAILED under the claim token.

        Either both updates commit or neither does — never leave outbox FAILED while
        the message remains pending.
        """
        try:
            with self._uow_factory() as uow:
                if not uow.conversation_claims.verify_claim(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                ):
                    logger.info(
                        "Skipped permanent failure recording; claim token no longer active",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                            "claim_token": str(claim_token),
                        },
                    )
                    return

                # Message first: if outbox fails afterward, the whole UoW rolls back.
                vague = uow.messages.mark_vague(runtime_message_id=runtime_message_id)
                if vague is None:
                    logger.info(
                        "Skipped permanent failure recording; message not pending",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                        },
                    )
                    return

                failed = uow.outbox_events.mark_failed_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    error_message=str(error),
                )
                if failed is None:
                    # Force rollback of the vague update in this unit of work.
                    raise RetryableAgentRuntimeCoordinationError(
                        "Permanent outbox failure update did not apply under active claim"
                    )
        except RetryableAgentRuntimeCoordinationError:
            logger.info(
                "Rolled back permanent failure recording; outbox not marked failed",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "claim_token": str(claim_token),
                },
            )
            return

        logger.error(
            "Permanent coordination failure",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "error": str(error),
            },
        )

    def _retry_delay(self, attempt_count: int) -> timedelta:
        base = timedelta(seconds=self._settings.outbox_retry_base_seconds)
        maximum = timedelta(seconds=self._settings.outbox_retry_max_seconds)
        delay = base * (2 ** max(attempt_count, 0))
        return min(delay, maximum)

    @staticmethod
    def _to_view(message: RuntimeMessage) -> CoordinatorMessageView:
        group_number = None
        if message.group is not None:
            group_number = message.group.group_number
        return CoordinatorMessageView(
            ingress_message_id=message.ingress_message_id,
            message_id=message.message_id,
            reply_message_id=message.reply_message_id,
            text=message.text,
            attachment_type=message.attachment_type,
            group_number=group_number,
        )
