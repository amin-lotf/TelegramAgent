from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
)


class AsyncSqlAlchemyDownloadRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, request: DownloadRequest) -> DownloadRequest:
        self._session.add(request)
        await self._session.flush()
        return request

    async def get_by_job_id(self, job_id: UUID) -> DownloadRequest | None:
        result = await self._session.execute(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )
        return result.scalar_one_or_none()
