from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telegram_agent.core.telegram_ingress.db.async_session import AsyncSessionLocal
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import AsyncSqlAlchemyTelegramIngressUnitOfWork


@asynccontextmanager
async def async_telegram_ingress_uow_factory() -> AsyncIterator[AsyncSqlAlchemyTelegramIngressUnitOfWork]:
    async with AsyncSessionLocal() as session:
        async with AsyncSqlAlchemyTelegramIngressUnitOfWork(session) as uow:
            yield uow