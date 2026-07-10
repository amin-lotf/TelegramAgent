from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.models.content_processing import Job


class AsyncSqlAlchemyJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: Job) -> Job:
        self._session.add(job)
        await self._session.flush()
        return job

    async def get_by_id(self, job_id: UUID) -> Job | None:
        stmt = select(Job).where(Job.id == job_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(
        self,
        job_id: UUID,
        **fields,
    ) -> Job | None:
        job = await self.get_by_id(job_id)

        if job is None:
            return None

        for key, value in fields.items():
            setattr(job, key, value)

        await self._session.flush()
        return job