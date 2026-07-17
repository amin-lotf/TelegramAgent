from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.models.content_processing import (
    JobCompletionExpectation,
)


class AsyncSqlAlchemyJobExpectationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        expectation: JobCompletionExpectation,
    ) -> JobCompletionExpectation:
        self._session.add(expectation)
        await self._session.flush()
        return expectation

    async def get_by_job_id(self, job_id: UUID) -> JobCompletionExpectation | None:
        result = await self._session.execute(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )
        return result.scalar_one_or_none()
