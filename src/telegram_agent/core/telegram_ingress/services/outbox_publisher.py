from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta

from pydantic import ValidationError

from telegram_agent.core.common.exceptions import (
    AgentRuntimeBadResponseError,
    AgentRuntimeUnavailableError,
    ContentProcessingBadResponseError,
    ContentProcessingUnavailableError,
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_ingress.clients.agent_runtime import AgentRuntimeClient
from telegram_agent.core.telegram_ingress.clients.content_processing import ContentProcessingClient
from telegram_agent.core.telegram_ingress.clients.telegram_bot import TelegramBotClient
from telegram_agent.core.telegram_ingress.common.commands import (
    CancelAllSecondaryTasksPayload,
    RuntimeMessageBatchPayload,
)
from telegram_agent.core.telegram_ingress.common.results import OutboxDispatchResult
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.common.types import (
    ConversationStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.uow.sync_telegram_ingress import (
    SyncSqlAlchemyTelegramIngressUnitOfWork,
)
from telegram_agent.core.telegram_ingress.db.uow.sync_uow_factory import (
    sync_telegram_ingress_uow_factory,
)

logger = logging.getLogger(__name__)


class OutboxPublisher:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyTelegramIngressUnitOfWork],
        ],
        agent_runtime_client: AgentRuntimeClient,
        batch_size: int,
        lease_timeout: timedelta,
        retry_base_delay: timedelta,
        retry_max_delay: timedelta,
        content_processing_client: ContentProcessingClient | None = None,
        telegram_bot_client: TelegramBotClient | None = None,
        lease_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._agent_runtime_client = agent_runtime_client
        self._batch_size = batch_size
        self._lease_timeout = lease_timeout
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._content_processing_client = content_processing_client
        self._telegram_bot_client = telegram_bot_client
        self._lease_owner = lease_owner or self._default_lease_owner()

    @classmethod
    def from_settings(cls) -> "OutboxPublisher":
        runtime_token = settings.agent_runtime_service_token
        if runtime_token is None:
            raise RuntimeError("AGENT_RUNTIME_SERVICE_TOKEN must be configured")
        content_processing_token = settings.content_processing_service_token
        if content_processing_token is None:
            raise RuntimeError("CONTENT_PROCESSING_SERVICE_TOKEN must be configured")
        bot_token = settings.telegram_bot_token
        if bot_token is None:
            raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured")
        return cls(
            uow_factory=sync_telegram_ingress_uow_factory,
            agent_runtime_client=AgentRuntimeClient(
                base_url=settings.agent_runtime_base_url,
                token=runtime_token,
                timeout_seconds=settings.agent_runtime_request_timeout_seconds,
            ),
            batch_size=settings.outbox_dispatch_batch_size,
            lease_timeout=timedelta(seconds=settings.outbox_dispatch_lease_seconds),
            retry_base_delay=timedelta(seconds=settings.outbox_retry_base_seconds),
            retry_max_delay=timedelta(seconds=settings.outbox_retry_max_seconds),
            content_processing_client=ContentProcessingClient(
                base_url=settings.content_processing_base_url,
                token=content_processing_token,
            ),
            telegram_bot_client=TelegramBotClient(
                bot_token=bot_token,
                api_base_url=settings.telegram_api_base_url,
            ),
        )

    def dispatch_once(self) -> OutboxDispatchResult:
        with self._uow_factory() as uow:
            recovered_count = uow.outbox_events.recover_expired_leases(
                lease_timeout=self._lease_timeout,
            )
            events = uow.outbox_events.claim_available(
                batch_size=self._batch_size,
                lease_owner=self._lease_owner,
                lease_timeout=self._lease_timeout,
            )

        if recovered_count:
            logger.info(
                "Recovered expired Telegram-ingress outbox leases",
                extra={"recovered_count": recovered_count},
            )

        published = 0
        retryable_failures = 0
        permanent_failures = 0

        for event in events:
            try:
                self._dispatch_event(event)
            except (
                AgentRuntimeUnavailableError,
                ContentProcessingUnavailableError,
                TelegramDownloadError,
            ) as exc:
                retryable_failures += 1
                self._record_retryable_failure(event=event, error=exc)
                continue
            except (
                AgentRuntimeBadResponseError,
                ContentProcessingBadResponseError,
                TelegramDownloadPermanentError,
                ValidationError,
                RuntimeError,
            ) as exc:
                permanent_failures += 1
                self._mark_permanent_failure(
                    event=event,
                    error_message=str(exc),
                )
                continue

            with self._uow_factory() as uow:
                published_event = uow.outbox_events.mark_published(
                    event_id=event.id,
                    lease_owner=self._lease_owner,
                )
                if published_event is not None:
                    uow.user_messages.mark_dispatch_status_for_event(
                        dispatch_event_id=event.id,
                        status=ConversationStatus.DISPATCHED,
                    )

            if published_event is None:
                logger.warning(
                    "Runtime batch was accepted but its outbox lease was no longer owned",
                    extra={"outbox_event_id": str(event.id)},
                )
            else:
                published += 1
                logger.info(
                    "Published Telegram-ingress outbox event",
                    extra={
                        "outbox_event_id": str(event.id),
                        "chat_id": event.chat_id,
                        "event_type": event.event_type,
                    },
                )

        return OutboxDispatchResult(
            claimed=len(events),
            published=published,
            retryable_failures=retryable_failures,
            permanent_failures=permanent_failures,
        )

    def _dispatch_event(self, event: ConversationOutboxEvent) -> None:
        if event.event_type == OutboxEventType.CONVERSATION_MESSAGES_ENQUEUED:
            payload = RuntimeMessageBatchPayload.model_validate(event.payload)
            self._agent_runtime_client.submit_message_batch(
                batch_id=event.id,
                idempotency_key=event.idempotency_key,
                payload=payload,
            )
            return
        if event.event_type == OutboxEventType.CANCEL_ALL_SECONDARY_TASKS_REQUESTED:
            if self._content_processing_client is None:
                raise RuntimeError(
                    "Content-processing client is not configured for cancel-all"
                )
            if self._telegram_bot_client is None:
                raise RuntimeError("Telegram bot client is not configured for cancel-all")
            payload = CancelAllSecondaryTasksPayload.model_validate(event.payload)
            result = self._content_processing_client.cancel_all_secondary_tasks(
                payload=payload,
                idempotency_key=event.idempotency_key,
            )
            count = result.matched_active_count
            noun = "request" if count == 1 else "requests"
            text = (
                f"Cancellation registered for {count} active dub/subtitle {noun}. "
                "Any earlier request still in the queue is covered too."
            )
            self._telegram_bot_client.send_message(
                chat_id=payload.chat_id,
                text=text,
                reply_to_message_id=payload.command_message_id,
            )
            return
        raise RuntimeError(f"Unsupported outbox event type: {event.event_type}")

    def _record_retryable_failure(
        self,
        *,
        event: ConversationOutboxEvent,
        error: Exception,
    ) -> None:
        next_available_at = utcnow() + self._retry_delay(event.attempt_count)
        with self._uow_factory() as uow:
            failed_event = uow.outbox_events.record_failure(
                event_id=event.id,
                lease_owner=self._lease_owner,
                error_message=str(error),
                next_available_at=next_available_at,
            )

        if failed_event is None:
            logger.warning(
                "Runtime publication failure could not be recorded",
                extra={"outbox_event_id": str(event.id), "error": str(error)},
            )
            return

        logger.warning(
            "Runtime publication failed; scheduled retry",
            extra={
                "outbox_event_id": str(event.id),
                "attempt_count": failed_event.attempt_count,
                "next_available_at": next_available_at.isoformat(),
                "error": str(error),
            },
        )

    def _mark_permanent_failure(
        self,
        *,
        event: ConversationOutboxEvent,
        error_message: str,
    ) -> None:
        with self._uow_factory() as uow:
            failed_event = uow.outbox_events.mark_failed(
                event_id=event.id,
                lease_owner=self._lease_owner,
                error_message=error_message,
            )
            if failed_event is not None:
                uow.user_messages.mark_dispatch_status_for_event(
                    dispatch_event_id=event.id,
                    status=ConversationStatus.FAILED,
                )

        if failed_event is None:
            logger.warning(
                "Permanent runtime publication failure could not be recorded",
                extra={"outbox_event_id": str(event.id), "error": error_message},
            )
            return

        logger.error(
            "Runtime message batch permanently failed",
            extra={
                "outbox_event_id": str(event.id),
                "chat_id": event.chat_id,
                "error": error_message,
            },
        )

    def _retry_delay(self, attempt_count: int) -> timedelta:
        multiplier = 2 ** max(attempt_count, 0)
        delay = self._retry_base_delay * multiplier
        return min(delay, self._retry_max_delay)

    @staticmethod
    def _default_lease_owner() -> str:
        return f"{socket.gethostname()}:{os.getpid()}"
