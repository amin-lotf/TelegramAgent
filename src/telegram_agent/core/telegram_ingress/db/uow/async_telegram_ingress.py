from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.telegram_ingress.db.repositories.async_outbox import AsyncSqlAlchemyConversationOutboxRepository
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import AsyncSqlAlchemyUserMessageRepository


class AsyncSqlAlchemyTelegramIngressUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.outbox_events = AsyncSqlAlchemyConversationOutboxRepository(session)
        self.user_messages = AsyncSqlAlchemyUserMessageRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def flush(self) -> None:
        await self._session.flush()

    async def __aenter__(self) -> "AsyncSqlAlchemyTelegramIngressUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
