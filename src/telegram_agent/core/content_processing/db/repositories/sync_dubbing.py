from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.content_processing.common.types import DubbingStatus
from telegram_agent.core.content_processing.db.models.content_processing import (
    DubbingArtifact,
    DubbingWorkflow,
)


class SyncSqlAlchemyDubbingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_job_id(self, job_id: UUID) -> DubbingWorkflow | None:
        return self._session.scalar(
            select(DubbingWorkflow).where(DubbingWorkflow.job_id == job_id)
        )

    def add(self, workflow: DubbingWorkflow) -> DubbingWorkflow:
        self._session.add(workflow)
        self._session.flush()
        return workflow

    def claim(
        self,
        *,
        job_id: UUID,
        ready_status: DubbingStatus,
        running_status: DubbingStatus,
        lease_timeout: timedelta,
    ) -> DubbingWorkflow | None:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.cancellation_requested_at.is_(None),
                or_(
                    DubbingWorkflow.status == ready_status,
                    (
                        (DubbingWorkflow.status == running_status)
                        & (DubbingWorkflow.updated_at < stale_before)
                    ),
                ),
            )
            .values(
                status=running_status,
                error_message=None,
                updated_at=func.now(),
            )
            .returning(DubbingWorkflow)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def set_active_gpu_job(
        self,
        *,
        job_id: UUID,
        running_status: DubbingStatus,
        gpu_job_id: UUID,
    ) -> bool:
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status == running_status,
                DubbingWorkflow.cancellation_requested_at.is_(None),
            )
            .values(active_gpu_job_id=gpu_job_id, updated_at=func.now())
            .returning(DubbingWorkflow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def transition(
        self,
        *,
        job_id: UUID,
        from_status: DubbingStatus,
        to_status: DubbingStatus,
        clear_gpu_job: bool = False,
    ) -> bool:
        values: dict[str, object] = {
            "status": to_status,
            "error_message": None,
            "updated_at": func.now(),
        }
        if clear_gpu_job:
            values["active_gpu_job_id"] = None
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status == from_status,
                DubbingWorkflow.cancellation_requested_at.is_(None),
            )
            .values(**values)
            .returning(DubbingWorkflow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_retryable(
        self,
        *,
        job_id: UUID,
        from_status: DubbingStatus,
        to_status: DubbingStatus,
        error_message: str,
    ) -> None:
        self._session.execute(
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status == from_status,
                DubbingWorkflow.cancellation_requested_at.is_(None),
            )
            .values(
                status=to_status,
                error_message=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
        )

    def touch(self, *, job_id: UUID, status: DubbingStatus) -> bool:
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status == status,
                DubbingWorkflow.cancellation_requested_at.is_(None),
            )
            .values(updated_at=func.now())
            .returning(DubbingWorkflow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_failed(self, *, job_id: UUID, error_message: str) -> bool:
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status.not_in(
                    (DubbingStatus.READY_FOR_DELIVERY, DubbingStatus.CANCELLED, DubbingStatus.FAILED)
                ),
            )
            .values(
                status=DubbingStatus.FAILED,
                active_gpu_job_id=None,
                error_message=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
            .returning(DubbingWorkflow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def request_cancellation(self, *, job_id: UUID) -> DubbingWorkflow | None:
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status.not_in(
                    (DubbingStatus.READY_FOR_DELIVERY, DubbingStatus.CANCELLED, DubbingStatus.FAILED)
                ),
            )
            .values(
                status=DubbingStatus.CANCELLING,
                cancellation_requested_at=func.now(),
                updated_at=func.now(),
            )
            .returning(DubbingWorkflow)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_cancelled(self, *, job_id: UUID) -> bool:
        statement = (
            update(DubbingWorkflow)
            .where(
                DubbingWorkflow.job_id == job_id,
                DubbingWorkflow.status == DubbingStatus.CANCELLING,
            )
            .values(
                status=DubbingStatus.CANCELLED,
                active_gpu_job_id=None,
                updated_at=func.now(),
            )
            .returning(DubbingWorkflow.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def get_artifact(self, *, workflow_id: UUID, artifact_type: str) -> DubbingArtifact | None:
        return self._session.scalar(
            select(DubbingArtifact).where(
                DubbingArtifact.workflow_id == workflow_id,
                DubbingArtifact.artifact_type == artifact_type,
            )
        )

    def upsert_artifact(
        self,
        *,
        workflow_id: UUID,
        artifact_type: str,
        local_path: str,
        producer: str | None,
        size_bytes: int | None,
        metadata: dict[str, object] | None = None,
    ) -> DubbingArtifact:
        artifact = self.get_artifact(
            workflow_id=workflow_id, artifact_type=artifact_type
        )
        if artifact is None:
            artifact = DubbingArtifact(
                workflow_id=workflow_id,
                artifact_type=artifact_type,
                local_path=local_path,
                producer=producer,
                size_bytes=size_bytes,
                artifact_metadata=metadata,
            )
            self._session.add(artifact)
        else:
            artifact.local_path = local_path
            artifact.producer = producer
            artifact.size_bytes = size_bytes
            artifact.artifact_metadata = metadata
            artifact.updated_at = utcnow()
        self._session.flush()
        return artifact
