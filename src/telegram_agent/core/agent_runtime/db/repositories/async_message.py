from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.agent_runtime.db.models.runtime import RuntimeMessage


class AsyncSqlAlchemyRuntimeMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, message: RuntimeMessage) -> RuntimeMessage:
        self._session.add(message)
        return message

    async def get_by_id(self, message_id: UUID) -> RuntimeMessage | None:
        return await self._session.get(RuntimeMessage, message_id)

    async def get_by_ingress_message_id(
        self,
        ingress_message_id: UUID,
    ) -> RuntimeMessage | None:
        statement = select(RuntimeMessage).where(
            RuntimeMessage.ingress_message_id == ingress_message_id
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_by_batch_id(self, batch_id: UUID) -> list[RuntimeMessage]:
        statement = (
            select(RuntimeMessage)
            .where(RuntimeMessage.batch_id == batch_id)
            .order_by(RuntimeMessage.message_id)
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())
