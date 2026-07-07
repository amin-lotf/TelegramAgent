from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.telegram_ingress.db.repositories.user_message import SqlAlchemyUserMessageRepository


class SqlAlchemyTelegramIngressUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.user_requests = SqlAlchemyUserMessageRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def __aenter__(self) -> "SqlAlchemyTelegramIngressUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
