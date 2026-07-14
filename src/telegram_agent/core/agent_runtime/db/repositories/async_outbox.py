from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.agent_runtime.db.models.runtime import OutboxEvent


class AsyncSqlAlchemyOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> OutboxEvent:
        self._session.add(event)
        return event

    async def get_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(
            OutboxEvent.idempotency_key == idempotency_key
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_runtime_message_id(
        self,
        runtime_message_id: UUID,
    ) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(
            OutboxEvent.runtime_message_id == runtime_message_id
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
