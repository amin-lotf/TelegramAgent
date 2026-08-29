from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from telegram_agent.core.content_processing.common.results import (
    RegisterSecondaryTaskCancellationResult,
)
from telegram_agent.core.content_processing.common.types import (
    DubbingStatus,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    OutboxEvent,
    SecondaryTaskCancellation,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


class SyncSecondaryTaskCancellationService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [], AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork]
        ],
    ) -> None:
        self._uow_factory = uow_factory

    @classmethod
    def from_settings(cls) -> "SyncSecondaryTaskCancellationService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(uow_factory=sync_content_processing_uow_factory)

    def register(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        cutoff_message_id: int,
        idempotency_key: str,
    ) -> RegisterSecondaryTaskCancellationResult:
        try:
            with self._uow_factory() as uow:
                uow.secondary_task_cancellations.lock_scope(
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                )
                existing = uow.secondary_task_cancellations.get_by_idempotency_key(
                    idempotency_key
                )
                if existing is not None:
                    self._assert_same_scope(
                        existing=existing,
                        telegram_user_id=telegram_user_id,
                        chat_id=chat_id,
                        cutoff_message_id=cutoff_message_id,
                    )
                    return self._result(existing, created=False)

                cancellation = uow.secondary_task_cancellations.add(
                    SecondaryTaskCancellation(
                        telegram_user_id=telegram_user_id,
                        chat_id=chat_id,
                        cutoff_message_id=cutoff_message_id,
                        idempotency_key=idempotency_key,
                    )
                )
                requests = uow.download_requests.list_active_secondary_for_cancellation(
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    cutoff_message_id=cutoff_message_id,
                )
                matched = 0
                for request in requests:
                    if not uow.download_requests.request_bulk_cancellation(
                        request_id=request.id,
                        cancellation_id=cancellation.id,
                    ):
                        continue
                    next_status = uow.jobs.request_download_cancellation(
                        job_id=request.job_id
                    )
                    if next_status is None:
                        continue
                    matched += 1
                    workflow = uow.dubbing.get_by_job_id(request.job_id)
                    if workflow is not None:
                        uow.dubbing.request_cancellation(job_id=request.job_id)
                    if next_status == JobStatus.CANCELLED:
                        uow.download_requests.mark_bulk_cancelled(job_id=request.job_id)
                        uow.job_expectations.mark_satisfied(job_id=request.job_id)
                    else:
                        self._enqueue_cancellation(uow, job_id=request.job_id)

                if not uow.secondary_task_cancellations.set_matched_active_count(
                    cancellation_id=cancellation.id,
                    matched_active_count=matched,
                ):
                    raise RuntimeError("Cancellation result count could not be persisted")
                cancellation.matched_active_count = matched
                return self._result(cancellation, created=True)
        except IntegrityError:
            with self._uow_factory() as uow:
                existing = uow.secondary_task_cancellations.get_by_idempotency_key(
                    idempotency_key
                )
                if existing is None:
                    raise
                self._assert_same_scope(
                    existing=existing,
                    telegram_user_id=telegram_user_id,
                    chat_id=chat_id,
                    cutoff_message_id=cutoff_message_id,
                )
                return self._result(existing, created=False)

    def finalize(self, *, job_id: UUID) -> bool:
        with self._uow_factory() as uow:
            request = uow.download_requests.get_by_job_id(job_id)
            if request is None or request.cancelled_by_id is None:
                return False
            job = uow.jobs.get_by_id(job_id)
            if job is None:
                return False
            workflow = uow.dubbing.get_by_job_id(job_id)
            if workflow is not None and workflow.status == DubbingStatus.CANCELLING:
                uow.dubbing.mark_cancelled(job_id=job_id)
            if job.status == JobStatus.CANCELLING:
                uow.jobs.finalize_download_cancellation(job_id=job_id)
            elif job.status != JobStatus.CANCELLED:
                return False
            uow.download_requests.mark_bulk_cancelled(job_id=job_id)
            uow.job_expectations.mark_satisfied(job_id=job_id)
            return True

    @staticmethod
    def _enqueue_cancellation(
        uow: SyncSqlAlchemyContentProcessingUnitOfWork, *, job_id: UUID
    ) -> None:
        event_type = OutboxEventType.DOWNLOAD_CANCELLATION_REQUESTED
        key = f"{event_type.value}:{job_id}"
        if uow.outbox_events.get_by_idempotency_key(key) is None:
            uow.outbox_events.add(
                OutboxEvent(
                    event_type=event_type,
                    job_id=job_id,
                    idempotency_key=key,
                    payload={},
                )
            )

    @staticmethod
    def _assert_same_scope(
        *,
        existing: SecondaryTaskCancellation,
        telegram_user_id: int,
        chat_id: int,
        cutoff_message_id: int,
    ) -> None:
        if (
            existing.telegram_user_id != telegram_user_id
            or existing.chat_id != chat_id
            or existing.cutoff_message_id != cutoff_message_id
        ):
            raise ValueError("Cancellation idempotency key was reused for another scope")

    @staticmethod
    def _result(
        cancellation: SecondaryTaskCancellation, *, created: bool
    ) -> RegisterSecondaryTaskCancellationResult:
        return RegisterSecondaryTaskCancellationResult(
            cancellation_id=cancellation.id,
            cutoff_message_id=cancellation.cutoff_message_id,
            matched_active_count=cancellation.matched_active_count,
            created=created,
        )
