from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuExecutionSlot, GpuJob


class SyncSqlAlchemyGpuJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: GpuJob) -> GpuJob:
        self._session.add(job)
        self._session.flush()
        return job

    def get_by_id(self, job_id: UUID, *, for_update: bool = False) -> GpuJob | None:
        statement = select(GpuJob).where(GpuJob.id == job_id)
        if for_update:
            statement = statement.with_for_update()
        return self._session.scalar(statement)

    def get_by_idempotency_key(self, idempotency_key: str) -> GpuJob | None:
        return self._session.scalar(
            select(GpuJob).where(GpuJob.idempotency_key == idempotency_key)
        )

    def claim(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        lease_timeout: timedelta,
    ) -> GpuJob | None:
        now = utcnow()
        slot = self._get_slot(for_update=True)
        if (
            slot.gpu_job_id is not None
            and slot.gpu_job_id != job_id
            and slot.lease_expires_at is not None
            and slot.lease_expires_at > now
        ):
            return None
        job = self.get_by_id(job_id, for_update=True)
        if job is None:
            return None
        schedulable = (
            job.status in (GpuJobStatus.PENDING, GpuJobStatus.RETRYING)
            and job.available_at <= now
        )
        stale_running = (
            job.status == GpuJobStatus.RUNNING
            and job.lease_expires_at is not None
            and job.lease_expires_at <= now
        )
        if not schedulable and not stale_running:
            return None
        if job.cancellation_requested_at is not None:
            previous_worker_id = job.worker_id
            self._set_canceled(job)
            self._release_slot(job_id=job.id, worker_id=previous_worker_id)
            return None
        if job.attempt_count >= job.max_attempts:
            previous_worker_id = job.worker_id
            self._set_failed(
                job,
                error_kind="worker_lost",
                error_message="GPU job attempt limit exhausted during recovery",
            )
            self._release_slot(job_id=job.id, worker_id=previous_worker_id)
            return None

        job.status = GpuJobStatus.RUNNING
        job.attempt_count += 1
        job.worker_id = worker_id
        job.process_id = None
        job.started_at = now
        job.finished_at = None
        job.heartbeat_at = now
        job.lease_expires_at = now + lease_timeout
        job.error_kind = None
        job.error_message = None
        job.updated_at = now
        slot.gpu_job_id = job.id
        slot.worker_id = worker_id
        slot.lease_expires_at = now + lease_timeout
        slot.updated_at = now
        self._session.flush()
        return job

    def set_process_id(self, *, job_id: UUID, worker_id: str, process_id: int) -> bool:
        statement = (
            update(GpuJob)
            .where(
                GpuJob.id == job_id,
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.worker_id == worker_id,
            )
            .values(process_id=process_id, updated_at=func.now())
            .returning(GpuJob.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def heartbeat(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        lease_timeout: timedelta,
    ) -> bool:
        now = utcnow()
        slot = self._get_slot(for_update=True)
        if slot.gpu_job_id != job_id or slot.worker_id != worker_id:
            return False
        statement = (
            update(GpuJob)
            .where(
                GpuJob.id == job_id,
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.worker_id == worker_id,
            )
            .values(
                heartbeat_at=now,
                lease_expires_at=now + lease_timeout,
                updated_at=now,
            )
            .returning(GpuJob.id)
        )
        updated = self._session.execute(statement).scalar_one_or_none() is not None
        if updated:
            slot.lease_expires_at = now + lease_timeout
            slot.updated_at = now
        return updated

    def cancellation_requested(self, *, job_id: UUID, worker_id: str) -> bool:
        statement = select(GpuJob.cancellation_requested_at).where(
            GpuJob.id == job_id,
            GpuJob.status == GpuJobStatus.RUNNING,
            GpuJob.worker_id == worker_id,
        )
        return self._session.scalar(statement) is not None

    def request_cancellation(self, *, job_id: UUID) -> GpuJob | None:
        now = utcnow()
        job = self.get_by_id(job_id, for_update=True)
        if job is None:
            return None
        if job.status in (GpuJobStatus.PENDING, GpuJobStatus.RETRYING):
            job.cancellation_requested_at = now
            self._set_canceled(job)
        elif job.status == GpuJobStatus.RUNNING:
            job.cancellation_requested_at = job.cancellation_requested_at or now
            job.updated_at = now
        self._session.flush()
        return job

    def mark_succeeded(self, *, job_id: UUID, worker_id: str) -> bool:
        now = utcnow()
        self._get_slot(for_update=True)
        statement = (
            update(GpuJob)
            .where(
                GpuJob.id == job_id,
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.worker_id == worker_id,
                GpuJob.cancellation_requested_at.is_(None),
            )
            .values(
                status=GpuJobStatus.SUCCEEDED,
                process_id=None,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                error_kind=None,
                error_message=None,
                finished_at=now,
                updated_at=now,
            )
            .returning(GpuJob.id)
        )
        updated = self._session.execute(statement).scalar_one_or_none() is not None
        if updated:
            self._release_slot(job_id=job_id, worker_id=worker_id)
        return updated

    def mark_canceled(self, *, job_id: UUID, worker_id: str) -> bool:
        now = utcnow()
        self._get_slot(for_update=True)
        statement = (
            update(GpuJob)
            .where(
                GpuJob.id == job_id,
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.worker_id == worker_id,
            )
            .values(
                status=GpuJobStatus.CANCELED,
                process_id=None,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                finished_at=now,
                updated_at=now,
            )
            .returning(GpuJob.id)
        )
        updated = self._session.execute(statement).scalar_one_or_none() is not None
        if updated:
            self._release_slot(job_id=job_id, worker_id=worker_id)
        return updated

    def mark_failed(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_kind: str,
        error_message: str,
    ) -> bool:
        now = utcnow()
        self._get_slot(for_update=True)
        statement = (
            update(GpuJob)
            .where(
                GpuJob.id == job_id,
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.worker_id == worker_id,
            )
            .values(
                status=GpuJobStatus.FAILED,
                process_id=None,
                worker_id=None,
                heartbeat_at=None,
                lease_expires_at=None,
                error_kind=error_kind,
                error_message=clean_error_message(error_message, max_length=4000),
                finished_at=now,
                updated_at=now,
            )
            .returning(GpuJob.id)
        )
        updated = self._session.execute(statement).scalar_one_or_none() is not None
        if updated:
            self._release_slot(job_id=job_id, worker_id=worker_id)
        return updated

    def mark_retrying(
        self,
        *,
        job_id: UUID,
        worker_id: str,
        error_kind: str,
        error_message: str,
        retry_delay: timedelta,
    ) -> GpuJob | None:
        now = utcnow()
        self._get_slot(for_update=True)
        job = self.get_by_id(job_id, for_update=True)
        if (
            job is None
            or job.status != GpuJobStatus.RUNNING
            or job.worker_id != worker_id
        ):
            return None
        if job.cancellation_requested_at is not None:
            self._set_canceled(job)
        elif job.attempt_count >= job.max_attempts:
            self._set_failed(job, error_kind=error_kind, error_message=error_message)
        else:
            job.status = GpuJobStatus.RETRYING
            job.available_at = now + retry_delay
            job.process_id = None
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.error_kind = error_kind
            job.error_message = clean_error_message(error_message, max_length=4000)
            job.finished_at = None
            job.updated_at = now
        self._session.flush()
        self._release_slot(job_id=job_id, worker_id=worker_id)
        return job

    def list_stale_running(self, *, limit: int) -> list[GpuJob]:
        now = utcnow()
        self._get_slot(for_update=True)
        statement = (
            select(GpuJob)
            .where(
                GpuJob.status == GpuJobStatus.RUNNING,
                GpuJob.lease_expires_at.is_not(None),
                GpuJob.lease_expires_at <= now,
            )
            .order_by(GpuJob.lease_expires_at, GpuJob.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(self._session.scalars(statement))

    def recover_stale(self, job: GpuJob, *, retry_delay: timedelta) -> GpuJobStatus:
        now = utcnow()
        previous_worker_id = job.worker_id
        if job.cancellation_requested_at is not None:
            self._set_canceled(job)
        elif job.attempt_count >= job.max_attempts:
            self._set_failed(
                job,
                error_kind="worker_lost",
                error_message="GPU worker lease expired and attempt limit was exhausted",
            )
        else:
            job.status = GpuJobStatus.RETRYING
            job.available_at = now + retry_delay
            job.process_id = None
            job.worker_id = None
            job.heartbeat_at = None
            job.lease_expires_at = None
            job.error_kind = "worker_lost"
            job.error_message = "GPU worker lease expired before the workload completed"
            job.updated_at = now
        self._session.flush()
        self._release_slot(job_id=job.id, worker_id=previous_worker_id)
        return job.status

    def slot_is_held_by_another_job(self, *, job_id: UUID) -> bool:
        slot = self._get_slot()
        return (
            slot.gpu_job_id is not None
            and slot.gpu_job_id != job_id
            and slot.lease_expires_at is not None
            and slot.lease_expires_at > utcnow()
        )

    def _get_slot(self, *, for_update: bool = False) -> GpuExecutionSlot:
        statement = select(GpuExecutionSlot).where(GpuExecutionSlot.id == 1)
        if for_update:
            statement = statement.with_for_update()
        slot = self._session.scalar(statement)
        if slot is None:
            slot = GpuExecutionSlot(id=1)
            self._session.add(slot)
            self._session.flush()
        return slot

    def _release_slot(self, *, job_id: UUID, worker_id: str | None) -> None:
        slot = self._get_slot(for_update=True)
        if slot.gpu_job_id != job_id:
            return
        if worker_id is not None and slot.worker_id != worker_id:
            return
        slot.gpu_job_id = None
        slot.worker_id = None
        slot.lease_expires_at = None
        slot.updated_at = utcnow()

    @staticmethod
    def _set_canceled(job: GpuJob) -> None:
        now = utcnow()
        job.status = GpuJobStatus.CANCELED
        job.process_id = None
        job.worker_id = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.finished_at = now
        job.updated_at = now

    @staticmethod
    def _set_failed(job: GpuJob, *, error_kind: str, error_message: str) -> None:
        now = utcnow()
        job.status = GpuJobStatus.FAILED
        job.process_id = None
        job.worker_id = None
        job.heartbeat_at = None
        job.lease_expires_at = None
        job.error_kind = error_kind
        job.error_message = clean_error_message(error_message, max_length=4000)
        job.finished_at = now
        job.updated_at = now
