from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telegram_agent.core.telegram_auth.db.async_session import AsyncSessionLocal
from telegram_agent.core.telegram_auth.db.uow.async_telegram_auth import SqlAlchemyTelegramAuthUnitOfWork


@asynccontextmanager
async def telegram_auth_uow_factory() -> AsyncIterator[SqlAlchemyTelegramAuthUnitOfWork]:
    async with AsyncSessionLocal() as session:
        async with SqlAlchemyTelegramAuthUnitOfWork(session) as uow:
            yield uow