from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.types import JobStatus
from telegram_agent.core.content_processing.db.models.content_processing import Job


class SyncSqlAlchemyJobRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, job_id: UUID) -> Job | None:
        stmt = select(Job).where(Job.id == job_id)
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def claim_for_download(self, job_id: UUID) -> Job | None:
        stmt = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status == JobStatus.QUEUED,
            )
            .values(
                status=JobStatus.RUNNING,
                updated_at=func.now(),
            )
            .returning(Job)
        )

        result = self._session.execute(stmt)
        return result.scalar_one_or_none()
