from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from telegram_agent.core.agent_runtime.clients.llm_gateway import LlmGatewayClient
from telegram_agent.core.agent_runtime.clients.telegram_ingress import (
    TelegramIngressClient,
)
from telegram_agent.core.agent_runtime.common.models import DownloadAgentDecision
from telegram_agent.core.agent_runtime.common.results import (
    ConversationDownloadHandlerResult,
    MessageDownloadHandlerResult,
)
from telegram_agent.core.agent_runtime.common.settings import Settings, settings
from telegram_agent.core.agent_runtime.common.types import (
    AgentMessageRole,
    OutboxEventType,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    AgentMessage,
    OutboxEvent,
)
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
from telegram_agent.core.agent_runtime.prompts.download_agent import (
    build_download_agent_prompts,
)
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import utcnow

logger = logging.getLogger(__name__)

DOWNLOADABLE_MEDIA_TYPES = frozenset(
    {
        TelegramAttachmentType.VIDEO,
        TelegramAttachmentType.AUDIO,
        TelegramAttachmentType.DOCUMENT,
    }
)


class SyncDownloadHandlerService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyAgentRuntimeUnitOfWork],
        ],
        llm_gateway_client: LlmGatewayClient,
        telegram_ingress_client: TelegramIngressClient,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._llm_gateway_client = llm_gateway_client
        self._telegram_ingress_client = telegram_ingress_client
        self._settings = settings

    @classmethod
    def from_settings(
        cls,
        *,
        llm_gateway_client: LlmGatewayClient | None = None,
        telegram_ingress_client: TelegramIngressClient | None = None,
    ) -> "SyncDownloadHandlerService":
        if llm_gateway_client is None:
            if settings.llm_gateway_service_token is None:
                raise RuntimeError("LLM_GATEWAY_SERVICE_TOKEN must be configured")
            llm_gateway_client = LlmGatewayClient(
                base_url=settings.llm_gateway_base_url,
                token=settings.llm_gateway_service_token,
                timeout_seconds=settings.llm_gateway_request_timeout_seconds,
            )
        if telegram_ingress_client is None:
            telegram_ingress_client = TelegramIngressClient(
                base_url=settings.telegram_ingress_base_url,
                token=settings.telegram_ingress_service_token,
                timeout_seconds=settings.telegram_ingress_request_timeout_seconds,
            )
        return cls(
            uow_factory=sync_agent_runtime_uow_factory,
            llm_gateway_client=llm_gateway_client,
            telegram_ingress_client=telegram_ingress_client,
            settings=settings,
        )

    def process_conversation(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
    ) -> ConversationDownloadHandlerResult:
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
                    "Skipping download handler without a valid claim token",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                    },
                )
                return ConversationDownloadHandlerResult(
                    chat_id=chat_id,
                    processed=0,
                    results=(),
                )

            pending_events = uow.outbox_events.list_unresolved_for_chat_by_type(
                chat_id=chat_id,
                event_type=OutboxEventType.DOWNLOAD_HANDLER,
                limit=self._settings.coordination_message_batch_size,
            )
            message_ids = [event.runtime_message_id for event in pending_events]

        results: list[MessageDownloadHandlerResult] = []
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
                            "Stopping download handler; claim token no longer valid",
                            extra={
                                "chat_id": chat_id,
                                "claim_token": str(claim_token),
                            },
                        )
                        return ConversationDownloadHandlerResult(
                            chat_id=chat_id,
                            processed=len(results),
                            results=tuple(results),
                        )

                result = self._handle_single_message(
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

        return ConversationDownloadHandlerResult(
            chat_id=chat_id,
            processed=len(results),
            results=tuple(results),
        )

    def _handle_single_message(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageDownloadHandlerResult | None:
        load_result = self._load_and_maybe_early_exit(
            chat_id=chat_id,
            runtime_message_id=runtime_message_id,
            claim_token=claim_token,
            lease_timeout=lease_timeout,
        )
        if load_result is None:
            return None
        if isinstance(load_result, MessageDownloadHandlerResult):
            return load_result
        if isinstance(load_result, PermanentAgentRuntimeCoordinationError):
            self._record_permanent_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                error=load_result,
            )
            return None
        if isinstance(load_result, RetryableAgentRuntimeCoordinationError):
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                error=load_result,
            )
            return None

        (
            group_id,
            group_texts,
            trigger_ingress_message_id,
            trigger_telegram_user_id,
            trigger_message_id,
            media_ingress_message_id,
            media_message_id,
            media_type,
            group_message_ids,
        ) = load_result

        try:
            prompts = build_download_agent_prompts(
                media_type=media_type,
                group_texts=group_texts,
                media_message_id=media_message_id,
            )
            generation = self._llm_gateway_client.extract_download_request(
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
                media_type=prompts.media_type,
            )
            try:
                decision = DownloadAgentDecision.model_validate(generation.output)
            except ValidationError as exc:
                raise RetryableAgentRuntimeCoordinationError(
                    "LLM gateway returned an invalid download-agent extraction"
                ) from exc

            if not decision.is_download_request:
                return self._apply_invalid_request(
                    chat_id=chat_id,
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                    group_id=group_id,
                    group_message_ids=group_message_ids,
                    trigger_ingress_message_id=trigger_ingress_message_id,
                    trigger_telegram_user_id=trigger_telegram_user_id,
                    decision=decision,
                )

            return self._apply_success(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                group_id=group_id,
                group_message_ids=group_message_ids,
                trigger_ingress_message_id=trigger_ingress_message_id,
                trigger_telegram_user_id=trigger_telegram_user_id,
                trigger_message_id=trigger_message_id,
                media_ingress_message_id=media_ingress_message_id,
                media_type=media_type,
                decision=decision,
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
                lease_timeout=lease_timeout,
                error=exc,
            )
            return None
        except Exception as exc:
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                error=exc,
            )
            logger.exception(
                "Unexpected download handler failure",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                },
            )
            return None

    def _load_and_maybe_early_exit(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> (
        MessageDownloadHandlerResult
        | tuple[
            UUID,
            list[str],
            UUID,
            int,
            int,
            UUID,
            int,
            TelegramAttachmentType,
            list[UUID],
        ]
        | PermanentAgentRuntimeCoordinationError
        | RetryableAgentRuntimeCoordinationError
        | None
    ):
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                return None

            message = uow.messages.get_by_id(runtime_message_id)
            if message is None or message.chat_id != chat_id:
                return None
            # Download runs immediately after grouping (no intent classification step).
            if message.status not in (
                RuntimeMessageStatus.COORDINATED,
                RuntimeMessageStatus.CLASSIFIED,  # legacy in-flight messages
            ):
                return None

            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
            if head is None or head.runtime_message_id != runtime_message_id:
                return None
            if head.event_type != OutboxEventType.DOWNLOAD_HANDLER.value:
                return None

            if message.group_id is None:
                return PermanentAgentRuntimeCoordinationError(
                    "Download handler requires a grouped message"
                )

            group_messages = uow.messages.list_for_chat_group(
                chat_id=chat_id,
                group_id=message.group_id,
            )
            group_id = message.group_id

            existing_agent = uow.agent_messages.get_by_group_and_role(
                group_id=group_id,
                role=AgentMessageRole.DOWNLOAD_AGENT,
            )
            group_message_ids = [item.id for item in group_messages]
            if existing_agent is not None:
                published_count = uow.outbox_events.mark_published_for_messages(
                    runtime_message_ids=group_message_ids,
                    claim_token=claim_token,
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if published_count < 1:
                    return RetryableAgentRuntimeCoordinationError(
                        "Failed to mark download-handler outbox published under active claim"
                    )
                return MessageDownloadHandlerResult(
                    runtime_message_id=runtime_message_id,
                    status=message.status.value,
                    early_exit=True,
                    agent_message_id=existing_agent.id,
                )

            downloadable = [
                item
                for item in group_messages
                if item.attachment_type in DOWNLOADABLE_MEDIA_TYPES
            ]
            group_texts = [
                item.text.strip()
                for item in group_messages
                if item.text is not None and item.text.strip()
            ]
            has_text_request = bool(group_texts)
            has_media = bool(downloadable)

            if not has_media or not has_text_request:
                published = uow.outbox_events.mark_published_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if published is None:
                    return RetryableAgentRuntimeCoordinationError(
                        "Failed to mark download-handler outbox published under active claim"
                    )
                logger.info(
                    "Download handler early-exit; incomplete group",
                    extra={
                        "chat_id": chat_id,
                        "runtime_message_id": str(runtime_message_id),
                        "group_id": str(group_id),
                        "has_media": has_media,
                        "has_text_request": has_text_request,
                    },
                )
                return MessageDownloadHandlerResult(
                    runtime_message_id=runtime_message_id,
                    status=message.status.value,
                    early_exit=True,
                )

            if len(downloadable) != 1:
                return PermanentAgentRuntimeCoordinationError(
                    "Download handler requires exactly one downloadable media attachment"
                )

            media_message = downloadable[0]
            if media_message.attachment_type is None:
                return PermanentAgentRuntimeCoordinationError(
                    "Downloadable media is missing attachment_type"
                )

            return (
                group_id,
                group_texts,
                message.ingress_message_id,
                message.telegram_user_id,
                message.message_id,
                media_message.ingress_message_id,
                media_message.message_id,
                media_message.attachment_type,
                group_message_ids,
            )

    def _apply_invalid_request(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
        group_id: UUID,
        group_message_ids: list[UUID],
        trigger_ingress_message_id: UUID,
        trigger_telegram_user_id: int,
        decision: DownloadAgentDecision,
    ) -> MessageDownloadHandlerResult:
        """User text was not a download request: notify and close outbox without handoff.

        Intentionally does not store an agent_message so a later clearer instruction
        in the same group can re-run the download agent.
        """
        notify_text = decision.assistant_text

        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                raise RetryableAgentRuntimeCoordinationError(
                    "Claim token is no longer valid"
                )

            existing = uow.agent_messages.get_by_group_and_role(
                group_id=group_id,
                role=AgentMessageRole.DOWNLOAD_AGENT,
            )
            if existing is not None:
                published_count = uow.outbox_events.mark_published_for_messages(
                    runtime_message_ids=group_message_ids,
                    claim_token=claim_token,
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if published_count < 1:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark download-handler outbox published under active claim"
                    )
                return MessageDownloadHandlerResult(
                    runtime_message_id=runtime_message_id,
                    status=RuntimeMessageStatus.COORDINATED.value,
                    early_exit=True,
                    agent_message_id=existing.id,
                )

            published_count = uow.outbox_events.mark_published_for_messages(
                runtime_message_ids=group_message_ids,
                claim_token=claim_token,
                event_type=OutboxEventType.DOWNLOAD_HANDLER,
            )
            if published_count < 1:
                raise RetryableAgentRuntimeCoordinationError(
                    "Failed to mark download-handler outbox published under active claim"
                )

        try:
            self._telegram_ingress_client.notify_request_preparing(
                chat_id=chat_id,
                telegram_user_id=trigger_telegram_user_id,
                text=notify_text,
                group_id=group_id,
                ingress_message_id=trigger_ingress_message_id,
            )
        except Exception as exc:
            logger.warning(
                "Best-effort telegram notify failed after invalid download request",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "error": str(exc),
                },
            )

        logger.info(
            "Download handler rejected non-download request",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "group_id": str(group_id),
            },
        )
        return MessageDownloadHandlerResult(
            runtime_message_id=runtime_message_id,
            status=RuntimeMessageStatus.COORDINATED.value,
            early_exit=False,
            agent_message_id=None,
        )

    def _apply_success(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
        group_id: UUID,
        group_message_ids: list[UUID],
        trigger_ingress_message_id: UUID,
        trigger_telegram_user_id: int,
        trigger_message_id: int,
        media_ingress_message_id: UUID,
        media_type: TelegramAttachmentType,
        decision: DownloadAgentDecision,
    ) -> MessageDownloadHandlerResult:
        agent_message_id = uuid4()
        notify_text = decision.assistant_text
        handoff_payload = self._build_handoff_payload(
            chat_id=chat_id,
            telegram_user_id=trigger_telegram_user_id,
            group_id=group_id,
            agent_message_id=agent_message_id,
            media_ingress_message_id=media_ingress_message_id,
            media_type=media_type,
            runtime_message_id=runtime_message_id,
            decision=decision,
        )

        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                raise RetryableAgentRuntimeCoordinationError(
                    "Claim token is no longer valid"
                )

            # Re-check idempotency under the claim before insert.
            existing = uow.agent_messages.get_by_group_and_role(
                group_id=group_id,
                role=AgentMessageRole.DOWNLOAD_AGENT,
            )
            if existing is not None:
                published_count = uow.outbox_events.mark_published_for_messages(
                    runtime_message_ids=group_message_ids,
                    claim_token=claim_token,
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if published_count < 1:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Failed to mark download-handler outbox published under active claim"
                    )
                return MessageDownloadHandlerResult(
                    runtime_message_id=runtime_message_id,
                    status=RuntimeMessageStatus.COORDINATED.value,
                    early_exit=True,
                    agent_message_id=existing.id,
                )

            agent_message = AgentMessage(
                id=agent_message_id,
                ingress_message_id=trigger_ingress_message_id,
                chat_id=chat_id,
                telegram_user_id=trigger_telegram_user_id,
                group_id=group_id,
                text=decision.assistant_text,
                role=AgentMessageRole.DOWNLOAD_AGENT,
            )
            uow.agent_messages.add(agent_message)

            handoff_key = f"agent_runtime:content_processing_handoff:{group_id}:v1"
            if uow.outbox_events.get_by_idempotency_key(handoff_key) is None:
                uow.outbox_events.add(
                    OutboxEvent(
                        event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF.value,
                        chat_id=chat_id,
                        runtime_message_id=runtime_message_id,
                        message_id=trigger_message_id,
                        idempotency_key=handoff_key,
                        payload=handoff_payload,
                    )
                )

            # Publish all group download-handler events so siblings are not blocked
            # behind the newly created content-processing handoff outbox.
            published_count = uow.outbox_events.mark_published_for_messages(
                runtime_message_ids=group_message_ids,
                claim_token=claim_token,
                event_type=OutboxEventType.DOWNLOAD_HANDLER,
            )
            if published_count < 1:
                raise RetryableAgentRuntimeCoordinationError(
                    "Failed to mark download-handler outbox published under active claim"
                )

        # Best-effort user notification after durable state is committed.
        try:
            self._telegram_ingress_client.notify_request_preparing(
                chat_id=chat_id,
                telegram_user_id=trigger_telegram_user_id,
                text=notify_text,
                group_id=group_id,
                ingress_message_id=trigger_ingress_message_id,
            )
        except Exception as exc:
            logger.warning(
                "Best-effort telegram notify failed after download handler success",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "error": str(exc),
                },
            )

        return MessageDownloadHandlerResult(
            runtime_message_id=runtime_message_id,
            status=RuntimeMessageStatus.COORDINATED.value,
            early_exit=False,
            agent_message_id=agent_message_id,
        )

    def _record_retryable_failure(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
        error: Exception,
    ) -> None:
        with self._uow_factory() as uow:
            event = uow.outbox_events.get_by_runtime_message_id(
                runtime_message_id,
                event_type=OutboxEventType.DOWNLOAD_HANDLER,
            )
            attempt_count = 0 if event is None else event.attempt_count

            if attempt_count < self._settings.outbox_max_attempts:
                next_available_at = utcnow() + self._retry_delay(attempt_count)
                updated = uow.outbox_events.record_failure_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    error_message=str(error),
                    next_available_at=next_available_at,
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if updated is None:
                    logger.info(
                        "Skipped retryable download-handler failure recording; "
                        "claim token no longer active",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                            "claim_token": str(claim_token),
                        },
                    )
                    return
                logger.warning(
                    "Retryable download handler failure",
                    extra={
                        "chat_id": chat_id,
                        "runtime_message_id": str(runtime_message_id),
                        "attempt_count": updated.attempt_count,
                        "next_available_at": next_available_at.isoformat(),
                        "max_attempts": self._settings.outbox_max_attempts,
                        "error": str(error),
                    },
                )
                return

        exhausted = RetryableAgentRuntimeCoordinationError(
            f"Retry limit exhausted after {attempt_count} attempts: {error}"
        )
        exhausted.__cause__ = error
        logger.error(
            "Retryable download handler failure exhausted max attempts; "
            "promoting to permanent",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "attempt_count": attempt_count,
                "max_attempts": self._settings.outbox_max_attempts,
                "error": str(error),
            },
        )
        self._record_permanent_failure(
            chat_id=chat_id,
            runtime_message_id=runtime_message_id,
            claim_token=claim_token,
            lease_timeout=lease_timeout,
            error=exhausted,
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
        try:
            with self._uow_factory() as uow:
                if not uow.conversation_claims.verify_claim(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                ):
                    logger.info(
                        "Skipped permanent download-handler failure recording; "
                        "claim token no longer active",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                            "claim_token": str(claim_token),
                        },
                    )
                    return

                failed_message = uow.messages.mark_download_handler_failed(
                    runtime_message_id=runtime_message_id,
                )
                if failed_message is None:
                    logger.info(
                        "Skipped permanent download-handler failure recording; "
                        "message not in classified download state",
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
                    event_type=OutboxEventType.DOWNLOAD_HANDLER,
                )
                if failed is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Permanent download-handler outbox failure update did not apply "
                        "under active claim"
                    )
        except RetryableAgentRuntimeCoordinationError:
            logger.info(
                "Rolled back permanent download-handler failure recording; "
                "outbox not marked failed",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "claim_token": str(claim_token),
                },
            )
            return

        logger.error(
            "Permanent download handler failure",
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
    def _build_handoff_payload(
        *,
        chat_id: int,
        telegram_user_id: int,
        group_id: UUID,
        agent_message_id: UUID,
        media_ingress_message_id: UUID,
        media_type: TelegramAttachmentType,
        runtime_message_id: UUID,
        decision: DownloadAgentDecision,
    ) -> dict[str, object]:
        """Build media-type-specific content-processing handoff outbox payload.

        Typed extraction fields are stored as first-class keys (not nested JSON)
        so the handoff consumer can call the matching content-processing endpoint.
        """
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "telegram_user_id": telegram_user_id,
            "group_id": str(group_id),
            "agent_message_id": str(agent_message_id),
            "media_ingress_message_id": str(media_ingress_message_id),
            "media_type": media_type.value,
            "assistant_text": decision.assistant_text,
            "runtime_message_id": str(runtime_message_id),
        }
        if media_type == TelegramAttachmentType.VIDEO:
            payload["requested_subtitle_language"] = decision.requested_subtitle_language
            payload["requested_dub_language"] = decision.requested_dub_language
        elif media_type == TelegramAttachmentType.AUDIO:
            payload["requested_language"] = decision.requested_language
        elif media_type == TelegramAttachmentType.DOCUMENT:
            # Video containers often arrive as documents; keep subtitle/dub fields
            # so handoff can route translation requests onto the video pipeline.
            payload["requested_subtitle_language"] = decision.requested_subtitle_language
            payload["requested_dub_language"] = decision.requested_dub_language
            payload["requested_format"] = decision.requested_format
        return payload
