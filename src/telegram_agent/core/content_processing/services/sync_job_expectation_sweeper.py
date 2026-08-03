from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.common.results import JobExpectationSweepResult
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    JobCompletionExpectation,
    OutboxEvent,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
    sync_content_processing_uow_factory,
)

logger = logging.getLogger(__name__)

_TERMINAL_JOB_STATUSES = frozenset(
    {
        JobStatus.EMOTION_EXTRACTED,
        # Historical terminals from when chunking/embedding were active.
        JobStatus.CHUNKED,
        JobStatus.EMBEDDED,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
        JobStatus.CANCELLED,
    }
)

# Jobs in these states may legitimately run longer than the initial SLA
# (e.g. WhisperX on hour-long media on CPU, or waiting between transcription
# and emotion extraction). Extend rather than time out while the stage lease is fresh.
_ACTIVE_JOB_STATUSES = frozenset(
    {
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.DOWNLOADED,
        JobStatus.TRANSCRIBING,
        JobStatus.TRANSCRIBED,
        JobStatus.EMOTION_EXTRACTING,
    }
)

_TIMEOUT_ERROR_MESSAGE = "Job completion expectation timed out"


class SyncJobExpectationSweeper:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        batch_size: int,
        lease_timeout: timedelta,
        resolved_retention: timedelta,
        active_grace: timedelta,
        lease_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._batch_size = batch_size
        self._lease_timeout = lease_timeout
        self._resolved_retention = resolved_retention
        self._active_grace = active_grace
        self._lease_owner = lease_owner or self._default_lease_owner()

    @classmethod
    def from_settings(cls) -> "SyncJobExpectationSweeper":
        # Grace must cover the longest in-flight stage (WhisperX or media lease).
        grace_seconds = max(
            settings.media_processing_lease_seconds,
            int(settings.whisperx_request_timeout_seconds),
            settings.job_expectation_default_seconds,
        )
        return cls(
            uow_factory=sync_content_processing_uow_factory,
            batch_size=settings.job_expectation_sweep_batch_size,
            lease_timeout=timedelta(
                seconds=settings.job_expectation_sweep_lease_seconds
            ),
            resolved_retention=timedelta(
                seconds=settings.job_expectation_resolved_retention_seconds
            ),
            active_grace=timedelta(seconds=grace_seconds),
        )

    def sweep_once(self) -> JobExpectationSweepResult:
        with self._uow_factory() as uow:
            recovered_count = uow.job_expectations.recover_expired_leases(
                lease_timeout=self._lease_timeout,
            )
            claimed = uow.job_expectations.claim_due(
                batch_size=self._batch_size,
                lease_owner=self._lease_owner,
                lease_timeout=self._lease_timeout,
            )

        if recovered_count:
            logger.info(
                "Recovered expired job completion expectation leases",
                extra={"recovered_count": recovered_count},
            )

        timed_out = 0
        satisfied = 0
        extended = 0
        for expectation in claimed:
            outcome = self._resolve_claimed(expectation)
            if outcome == "timed_out":
                timed_out += 1
            elif outcome == "satisfied":
                satisfied += 1
            elif outcome == "extended":
                extended += 1

        with self._uow_factory() as uow:
            deleted = uow.job_expectations.delete_resolved(
                older_than=utcnow() - self._resolved_retention,
                batch_size=self._batch_size,
            )

        if deleted:
            logger.info(
                "Purged resolved job completion expectations",
                extra={"deleted": deleted},
            )

        return JobExpectationSweepResult(
            claimed=len(claimed),
            timed_out=timed_out,
            satisfied=satisfied,
            extended=extended,
            recovered_leases=recovered_count,
            deleted=deleted,
        )

    def _resolve_claimed(self, expectation: JobCompletionExpectation) -> str:
        with self._uow_factory() as uow:
            job = uow.jobs.get_by_id(expectation.job_id)
            if job is None or job.status in _TERMINAL_JOB_STATUSES:
                resolved = uow.job_expectations.mark_satisfied_claimed(
                    expectation_id=expectation.id,
                    lease_owner=self._lease_owner,
                )
                if resolved is None:
                    logger.warning(
                        "Could not resolve already-terminal job expectation",
                        extra={
                            "expectation_id": str(expectation.id),
                            "job_id": str(expectation.job_id),
                        },
                    )
                    return "skipped"
                return "satisfied"

            # Still actively processing: push the deadline instead of killing work.
            if job.status in _ACTIVE_JOB_STATUSES:
                last_touch = job.updated_at or job.created_at
                if last_touch is not None and last_touch + self._active_grace >= utcnow():
                    new_due = utcnow() + self._active_grace
                    reopened = uow.job_expectations.reopen_with_due_at(
                        expectation_id=expectation.id,
                        lease_owner=self._lease_owner,
                        due_at=new_due,
                    )
                    if reopened is not None:
                        # Heartbeat so the next due sweep still sees a fresh lease.
                        uow.jobs.touch(job_id=expectation.job_id)
                        logger.info(
                            "Extended job completion expectation for active job",
                            extra={
                                "expectation_id": str(expectation.id),
                                "job_id": str(expectation.job_id),
                                "job_status": job.status.value,
                                "new_due_at": new_due.isoformat(),
                            },
                        )
                        return "extended"

            if not uow.jobs.mark_timed_out(
                job_id=expectation.job_id,
                error_message=_TIMEOUT_ERROR_MESSAGE,
            ):
                resolved = uow.job_expectations.mark_satisfied_claimed(
                    expectation_id=expectation.id,
                    lease_owner=self._lease_owner,
                )
                return "satisfied" if resolved is not None else "skipped"

            job = uow.jobs.get_by_id(expectation.job_id)
            if (
                job is not None
                and job.callback_required
                and job.status == JobStatus.TIMED_OUT
            ):
                event_type = OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED
                idempotency_key = f"{event_type.value}:{expectation.job_id}"
                if uow.outbox_events.get_by_idempotency_key(idempotency_key) is None:
                    uow.outbox_events.add(
                        OutboxEvent(
                            event_type=event_type,
                            job_id=expectation.job_id,
                            idempotency_key=idempotency_key,
                            payload={},
                        )
                    )

            resolved = uow.job_expectations.mark_timed_out(
                expectation_id=expectation.id,
                lease_owner=self._lease_owner,
                error_message=_TIMEOUT_ERROR_MESSAGE,
            )
            if resolved is None:
                logger.warning(
                    "Job timed out but expectation could not be marked timed_out",
                    extra={
                        "expectation_id": str(expectation.id),
                        "job_id": str(expectation.job_id),
                    },
                )
                return "skipped"

            logger.warning(
                "Job completion expectation timed out",
                extra={
                    "expectation_id": str(expectation.id),
                    "job_id": str(expectation.job_id),
                    "due_at": expectation.due_at.isoformat(),
                },
            )
            return "timed_out"

    @staticmethod
    def _default_lease_owner() -> str:
        return f"{socket.gethostname()}:{os.getpid()}"
