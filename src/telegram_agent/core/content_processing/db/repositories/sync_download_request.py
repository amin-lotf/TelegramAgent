from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
)


class SyncSqlAlchemyDownloadRequestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_job_id(self, job_id: UUID) -> DownloadRequest | None:
        return self._session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )

    def set_final_path(self, *, job_id: UUID, final_path: str) -> bool:
        statement = (
            update(DownloadRequest)
            .where(DownloadRequest.job_id == job_id)
            .values(final_path=final_path, updated_at=func.now())
            .returning(DownloadRequest.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None
