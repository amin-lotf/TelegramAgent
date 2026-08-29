from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta

from celery import Task

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.common.results import OutboxDispatchResult
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import OutboxEventType
from telegram_agent.core.content_processing.celery.tasks.download_delivery import (
    deliver_download_task,
)
from telegram_agent.core.content_processing.celery.tasks.download_preparation import (
    prepare_download_task,
)
from telegram_agent.core.content_processing.celery.tasks.download_cancellation import (
    cancel_download_task,
)
from telegram_agent.core.content_processing.celery.tasks.media_download import download_telegram_media_task
from telegram_agent.core.content_processing.celery.tasks.transcription import transcribe_media_task
from telegram_agent.core.content_processing.celery.tasks.telegram_ingress_callback import notify_telegram_ingress_task
from telegram_agent.core.content_processing.celery.tasks.dubbing import advance_dubbing_task
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.db.uow.sync_uow_factory import sync_content_processing_uow_factory

logger = logging.getLogger(__name__)


class OutboxDispatcher:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork]],
        batch_size: int,
        lease_timeout: timedelta,
        retry_base_delay: timedelta,
        retry_max_delay: timedelta,
        lease_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._lease_timeout = lease_timeout
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._lease_owner = lease_owner or self._default_lease_owner()
        self._task_by_event_type: dict[str, Task] = {
            OutboxEventType.CONTENT_PROCESSING_JOB_READY.value: download_telegram_media_task,
            OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value: transcribe_media_task,
            OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value: notify_telegram_ingress_task,
            OutboxEventType.DOWNLOAD_PREPARATION_READY.value: prepare_download_task,
            OutboxEventType.DOWNLOAD_READY_FOR_DELIVERY.value: deliver_download_task,
            OutboxEventType.DUBBING_SOURCE_RESOLVED.value: advance_dubbing_task,
            OutboxEventType.DUBBING_INPUTS_PREPARED.value: advance_dubbing_task,
            OutboxEventType.DUBBING_SPEECH_SYNTHESIZED.value: advance_dubbing_task,
            OutboxEventType.DUBBING_BACKGROUND_SEPARATED.value: advance_dubbing_task,
            OutboxEventType.DUBBING_CANCELLATION_REQUESTED.value: advance_dubbing_task,
            OutboxEventType.DOWNLOAD_FAILED_FOR_DELIVERY.value: deliver_download_task,
            OutboxEventType.DOWNLOAD_CANCELLATION_REQUESTED.value: cancel_download_task,
        }

    @classmethod
    def from_settings(cls) -> "OutboxDispatcher":
        return cls(
            uow_factory=sync_content_processing_uow_factory,
            batch_size=settings.outbox_dispatch_batch_size,
            lease_timeout=timedelta(seconds=settings.outbox_dispatch_lease_seconds),
            retry_base_delay=timedelta(seconds=settings.outbox_retry_base_seconds),
            retry_max_delay=timedelta(seconds=settings.outbox_retry_max_seconds),
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
                "Recovered expired outbox leases",
                extra={"recovered_count": recovered_count},
            )

        published = 0
        retryable_failures = 0
        permanent_failures = 0

        for event in events:
            task = self._task_by_event_type.get(event.event_type)
            if task is None:
                permanent_failures += 1
                self._mark_permanent_failure(
                    event=event,
                    error_message=f"Unsupported outbox event type: {event.event_type}",
                )
                continue

            job_id = event.job_id

            try:
                logger.info(
                    "Publishing outbox event",
                    extra={
                        "outbox_event_id": str(event.id),
                        "event_type": event.event_type,
                        "job_id": str(job_id),
                        "attempt_count": event.attempt_count,
                    },
                )
                task.apply_async(args=(str(job_id),))
            except Exception as exc:
                retryable_failures += 1
                self._record_retryable_failure(event=event, error=exc)
                continue

            with self._uow_factory() as uow:
                published_event = uow.outbox_events.mark_published(
                    event_id=event.id,
                    lease_owner=self._lease_owner,
                )

            if published_event is None:
                logger.warning(
                    "Outbox event was published but could not be marked published",
                    extra={"outbox_event_id": str(event.id)},
                )
            else:
                published += 1
                logger.info(
                    "Marked outbox event published",
                    extra={"outbox_event_id": str(event.id), "job_id": str(job_id)},
                )

        return OutboxDispatchResult(
            claimed=len(events),
            published=published,
            retryable_failures=retryable_failures,
            permanent_failures=permanent_failures,
        )

    def _record_retryable_failure(self, *, event: OutboxEvent, error: Exception) -> None:
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
                "Outbox event publication failed but failure could not be recorded",
                extra={"outbox_event_id": str(event.id), "error": str(error)},
            )
            return

        logger.warning(
            "Outbox event publication failed; scheduled retry",
            extra={
                "outbox_event_id": str(event.id),
                "next_available_at": next_available_at.isoformat(),
                "attempt_count": failed_event.attempt_count,
                "error": str(error),
            },
        )

    def _mark_permanent_failure(self, *, event: OutboxEvent, error_message: str) -> None:
        with self._uow_factory() as uow:
            failed_event = uow.outbox_events.mark_failed(
                event_id=event.id,
                lease_owner=self._lease_owner,
                error_message=error_message,
            )

        if failed_event is None:
            logger.warning(
                "Outbox event permanent failure could not be recorded",
                extra={"outbox_event_id": str(event.id), "error": error_message},
            )
            return

        logger.error(
            "Outbox event marked failed",
            extra={
                "outbox_event_id": str(event.id),
                "event_type": event.event_type,
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
