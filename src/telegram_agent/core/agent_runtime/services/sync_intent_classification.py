from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from uuid import UUID

from pydantic import ValidationError

from telegram_agent.core.agent_runtime.clients.llm_gateway import LlmGatewayClient
from telegram_agent.core.agent_runtime.common.models import (
    IntentClassificationDecision,
    IntentClassifierMessageView,
)
from telegram_agent.core.agent_runtime.common.results import (
    ConversationIntentClassificationResult,
    MessageIntentClassificationResult,
)
from telegram_agent.core.agent_runtime.common.settings import Settings, settings
from telegram_agent.core.agent_runtime.common.types import (
    MessageIntent,
    OutboxEventType,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import OutboxEvent, RuntimeMessage
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
from telegram_agent.core.agent_runtime.prompts.intent_classification import (
    build_intent_classification_prompts,
)
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)
from telegram_agent.core.common.utils import utcnow

logger = logging.getLogger(__name__)


class SyncIntentClassificationService:
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
    ) -> "SyncIntentClassificationService":
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
    ) -> ConversationIntentClassificationResult:
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
                    "Skipping intent classification without a valid claim token",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                    },
                )
                return ConversationIntentClassificationResult(
                    chat_id=chat_id,
                    processed=0,
                    results=(),
                )

            pending_events = uow.outbox_events.list_unresolved_for_chat_by_type(
                chat_id=chat_id,
                event_type=OutboxEventType.INTENT_CLASSIFIER,
                limit=self._settings.coordination_message_batch_size,
            )
            message_ids = [event.runtime_message_id for event in pending_events]

        results: list[MessageIntentClassificationResult] = []
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
                            "Stopping intent classification; claim token no longer valid",
                            extra={
                                "chat_id": chat_id,
                                "claim_token": str(claim_token),
                            },
                        )
                        return ConversationIntentClassificationResult(
                            chat_id=chat_id,
                            processed=len(results),
                            results=tuple(results),
                        )

                result = self._classify_single_message(
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

        return ConversationIntentClassificationResult(
            chat_id=chat_id,
            processed=len(results),
            results=tuple(results),
        )

    def _classify_single_message(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageIntentClassificationResult | None:
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
            if message.status not in (
                RuntimeMessageStatus.COORDINATED,
                RuntimeMessageStatus.CLASSIFYING,
            ):
                return None

            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
            if head is None or head.runtime_message_id != runtime_message_id:
                return None
            if head.event_type != OutboxEventType.INTENT_CLASSIFIER.value:
                return None

            classifying = uow.messages.mark_classifying(
                runtime_message_id=runtime_message_id,
            )
            if classifying is None:
                return None

            message_view = self._to_view(message)

        try:
            prompts = build_intent_classification_prompts(message=message_view)
            generation = self._llm_gateway_client.classify_intent(
                system_prompt=prompts.system_prompt,
                user_prompt=prompts.user_prompt,
            )
            try:
                decision = IntentClassificationDecision.model_validate(generation.output)
            except ValidationError as exc:
                raise RetryableAgentRuntimeCoordinationError(
                    "LLM gateway returned an invalid intent classification"
                ) from exc
            intent = MessageIntent(decision.intent.value)
            return self._apply_classification(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                intent=intent,
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
                "Unexpected intent classification failure",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                },
            )
            return None

    def _apply_classification(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        intent: MessageIntent,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageIntentClassificationResult:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                raise RetryableAgentRuntimeCoordinationError(
                    "Claim token is no longer valid"
                )

            updated = uow.messages.mark_classified(
                runtime_message_id=runtime_message_id,
                intent=intent,
            )
            if updated is None:
                raise RetryableAgentRuntimeCoordinationError(
                    "Failed to mark message as classified"
                )

            published = uow.outbox_events.mark_published_for_message(
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                event_type=OutboxEventType.INTENT_CLASSIFIER,
            )
            if published is None:
                raise RetryableAgentRuntimeCoordinationError(
                    "Failed to mark intent outbox published under active claim"
                )

            if intent == MessageIntent.DOWNLOAD_REQUEST:
                self._ensure_download_handler_outbox(uow=uow, message=updated)

            return MessageIntentClassificationResult(
                runtime_message_id=runtime_message_id,
                status=RuntimeMessageStatus.CLASSIFIED.value,
                intent=intent.value,
            )

    @staticmethod
    def _ensure_download_handler_outbox(
        *,
        uow: SyncSqlAlchemyAgentRuntimeUnitOfWork,
        message: RuntimeMessage,
    ) -> None:
        event_type = OutboxEventType.DOWNLOAD_HANDLER
        idempotency_key = (
            f"agent_runtime:download_handler:{message.ingress_message_id}:v1"
        )
        existing = uow.outbox_events.get_by_idempotency_key(idempotency_key)
        if existing is not None:
            return
        payload: dict[str, object] = {
            "ingress_message_id": str(message.ingress_message_id),
            "chat_id": message.chat_id,
            "message_id": message.message_id,
        }
        if message.group_id is not None:
            payload["group_id"] = str(message.group_id)
        uow.outbox_events.add(
            OutboxEvent(
                event_type=event_type.value,
                chat_id=message.chat_id,
                runtime_message_id=message.id,
                message_id=message.message_id,
                idempotency_key=idempotency_key,
                payload=payload,
            )
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
                event_type=OutboxEventType.INTENT_CLASSIFIER,
            )
            attempt_count = 0 if event is None else event.attempt_count

            if attempt_count < self._settings.outbox_max_attempts:
                next_available_at = utcnow() + self._retry_delay(attempt_count)
                updated = uow.outbox_events.record_failure_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    error_message=str(error),
                    next_available_at=next_available_at,
                    event_type=OutboxEventType.INTENT_CLASSIFIER,
                )
                if updated is None:
                    logger.info(
                        "Skipped retryable intent failure recording; "
                        "claim token no longer active",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                            "claim_token": str(claim_token),
                        },
                    )
                    return
                logger.warning(
                    "Retryable intent classification failure",
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
            "Retryable intent classification failure exhausted max attempts; "
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
        """Atomically mark message failed and intent outbox FAILED under the claim token."""
        try:
            with self._uow_factory() as uow:
                if not uow.conversation_claims.verify_claim(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                ):
                    logger.info(
                        "Skipped permanent intent failure recording; "
                        "claim token no longer active",
                        extra={
                            "chat_id": chat_id,
                            "runtime_message_id": str(runtime_message_id),
                            "claim_token": str(claim_token),
                        },
                    )
                    return

                failed_message = uow.messages.mark_classification_failed(
                    runtime_message_id=runtime_message_id,
                )
                if failed_message is None:
                    logger.info(
                        "Skipped permanent intent failure recording; "
                        "message not classifiable",
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
                    event_type=OutboxEventType.INTENT_CLASSIFIER,
                )
                if failed is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Permanent intent outbox failure update did not apply "
                        "under active claim"
                    )
        except RetryableAgentRuntimeCoordinationError:
            logger.info(
                "Rolled back permanent intent failure recording; outbox not marked failed",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                    "claim_token": str(claim_token),
                },
            )
            return

        logger.error(
            "Permanent intent classification failure",
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
    def _to_view(message: RuntimeMessage) -> IntentClassifierMessageView:
        return IntentClassifierMessageView(
            ingress_message_id=message.ingress_message_id,
            message_id=message.message_id,
            text=message.text,
            attachment_type=message.attachment_type,
        )
