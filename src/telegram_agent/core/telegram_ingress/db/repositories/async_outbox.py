from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent


class AsyncSqlAlchemyConversationOutboxRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: ConversationOutboxEvent) -> ConversationOutboxEvent:
        self._session.add(event)
        await self._session.flush()
        return event

    async def get_by_id(self, event_id: UUID) -> ConversationOutboxEvent | None:
        stmt=select(ConversationOutboxEvent).where(ConversationOutboxEvent.id == event_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> ConversationOutboxEvent | None:
        statement = select(ConversationOutboxEvent).where(
            ConversationOutboxEvent.idempotency_key == idempotency_key,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
