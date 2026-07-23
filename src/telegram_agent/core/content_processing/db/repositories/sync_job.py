from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.content_processing.common.types import JobStatus
from telegram_agent.core.content_processing.db.models.content_processing import Job


class SyncSqlAlchemyJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, job_id: UUID) -> Job | None:
        return self._session.scalar(select(Job).where(Job.id == job_id))

    def claim_for_download(self, job_id: UUID) -> Job | None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.QUEUED)
            .values(status=JobStatus.RUNNING, error_message=None, updated_at=func.now())
            .returning(Job)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def claim_download(self, *, job_id: UUID, lease_timeout: timedelta) -> bool:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.status == JobStatus.QUEUED,
                    (Job.status == JobStatus.RUNNING) & (Job.updated_at < stale_before),
                ),
            )
            .values(status=JobStatus.RUNNING, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def claim_transcription(self, *, job_id: UUID, lease_timeout: timedelta) -> bool:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.status == JobStatus.DOWNLOADED,
                    (Job.status == JobStatus.TRANSCRIBING) & (Job.updated_at < stale_before),
                ),
            )
            .values(status=JobStatus.TRANSCRIBING, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def complete_download(self, *, job_id: UUID, requires_transcription: bool) -> bool:
        next_status = JobStatus.DOWNLOADED if requires_transcription else JobStatus.COMPLETED
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.RUNNING)
            .values(status=next_status, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        if self._session.execute(statement).scalar_one_or_none() is not None:
            return True
        current_status = self._session.scalar(select(Job.status).where(Job.id == job_id))
        return current_status in (
            JobStatus.DOWNLOADED,
            JobStatus.TRANSCRIBING,
            JobStatus.TRANSCRIBED,
            JobStatus.CHUNKING,
            JobStatus.CHUNKED,
            JobStatus.EMBEDDING,
            JobStatus.EMBEDDED,
            JobStatus.COMPLETED,
        )

    def complete_transcription(self, *, job_id: UUID) -> bool:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.TRANSCRIBING)
            .values(status=JobStatus.TRANSCRIBED, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        if self._session.execute(statement).scalar_one_or_none() is not None:
            return True
        current_status = self._session.scalar(select(Job.status).where(Job.id == job_id))
        return current_status in (
            JobStatus.TRANSCRIBED,
            JobStatus.CHUNKING,
            JobStatus.CHUNKED,
            JobStatus.EMBEDDING,
            JobStatus.EMBEDDED,
        )

    def claim_chunking(self, *, job_id: UUID, lease_timeout: timedelta) -> bool:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.status == JobStatus.TRANSCRIBED,
                    (Job.status == JobStatus.CHUNKING) & (Job.updated_at < stale_before),
                ),
            )
            .values(status=JobStatus.CHUNKING, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def complete_chunking(self, *, job_id: UUID) -> bool:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.CHUNKING)
            .values(status=JobStatus.CHUNKED, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        if self._session.execute(statement).scalar_one_or_none() is not None:
            return True
        current_status = self._session.scalar(select(Job.status).where(Job.id == job_id))
        return current_status in (
            JobStatus.CHUNKED,
            JobStatus.EMBEDDING,
            JobStatus.EMBEDDED,
        )

    def claim_embedding(self, *, job_id: UUID, lease_timeout: timedelta) -> bool:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                or_(
                    Job.status == JobStatus.CHUNKED,
                    (Job.status == JobStatus.EMBEDDING) & (Job.updated_at < stale_before),
                ),
            )
            .values(status=JobStatus.EMBEDDING, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def complete_embedding(self, *, job_id: UUID) -> bool:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.status == JobStatus.EMBEDDING)
            .values(status=JobStatus.EMBEDDED, error_message=None, updated_at=func.now())
            .returning(Job.id)
        )
        if self._session.execute(statement).scalar_one_or_none() is not None:
            return True
        return (
            self._session.scalar(select(Job.status).where(Job.id == job_id))
            == JobStatus.EMBEDDED
        )

    def mark_download_retryable(self, *, job_id: UUID, error_message: str) -> None:
        self._mark_retryable(job_id=job_id, from_status=JobStatus.RUNNING, to_status=JobStatus.QUEUED, error_message=error_message)

    def mark_transcription_retryable(self, *, job_id: UUID, error_message: str) -> None:
        self._mark_retryable(job_id=job_id, from_status=JobStatus.TRANSCRIBING, to_status=JobStatus.DOWNLOADED, error_message=error_message)

    def mark_chunking_retryable(self, *, job_id: UUID, error_message: str) -> None:
        self._mark_retryable(
            job_id=job_id,
            from_status=JobStatus.CHUNKING,
            to_status=JobStatus.TRANSCRIBED,
            error_message=error_message,
        )

    def mark_embedding_retryable(self, *, job_id: UUID, error_message: str) -> None:
        self._mark_retryable(
            job_id=job_id,
            from_status=JobStatus.EMBEDDING,
            to_status=JobStatus.CHUNKED,
            error_message=error_message,
        )

    def mark_failed(self, *, job_id: UUID, error_message: str) -> bool:
        # CHUNKED is intermediate (awaits embedding); only EMBEDDED/COMPLETED are success terminals.
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.not_in(
                    (
                        JobStatus.EMBEDDED,
                        JobStatus.COMPLETED,
                        JobStatus.FAILED,
                        JobStatus.TIMED_OUT,
                        JobStatus.CANCELLED,
                    )
                ),
            )
            .values(
                status=JobStatus.FAILED,
                error_message=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def touch(self, *, job_id: UUID) -> bool:
        """Refresh updated_at for a non-terminal job (heartbeat for long stages)."""
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.not_in(
                    (
                        JobStatus.EMBEDDED,
                        JobStatus.COMPLETED,
                        JobStatus.FAILED,
                        JobStatus.TIMED_OUT,
                        JobStatus.CANCELLED,
                    )
                ),
            )
            .values(updated_at=func.now())
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_timed_out(self, *, job_id: UUID, error_message: str) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.not_in(
                    (
                        JobStatus.EMBEDDED,
                        JobStatus.COMPLETED,
                        JobStatus.FAILED,
                        JobStatus.TIMED_OUT,
                        JobStatus.CANCELLED,
                    )
                ),
            )
            .values(
                status=JobStatus.TIMED_OUT,
                error_message=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
            .returning(Job.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def _mark_retryable(self, *, job_id: UUID, from_status: JobStatus, to_status: JobStatus, error_message: str) -> None:
        self._session.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == from_status)
            .values(status=to_status, error_message=clean_error_message(error_message, max_length=2000), updated_at=func.now())
        )
