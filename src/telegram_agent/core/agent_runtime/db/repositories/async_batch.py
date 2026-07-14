from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.agent_runtime.db.models.runtime import RuntimeBatch


class AsyncSqlAlchemyRuntimeBatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, batch: RuntimeBatch) -> RuntimeBatch:
        self._session.add(batch)
        return batch

    async def get_by_id(self, batch_id: UUID) -> RuntimeBatch | None:
        return await self._session.get(RuntimeBatch, batch_id)

    async def get_by_idempotency_key(self, idempotency_key: str) -> RuntimeBatch | None:
        statement = select(RuntimeBatch).where(
            RuntimeBatch.idempotency_key == idempotency_key
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
