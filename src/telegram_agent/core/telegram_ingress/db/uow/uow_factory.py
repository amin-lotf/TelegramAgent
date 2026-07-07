from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telegram_agent.core.telegram_ingress.db.async_session import AsyncSessionLocal
from telegram_agent.core.telegram_ingress.db.uow.async_orchestration import SqlAlchemyOrchestrationUnitOfWork


@asynccontextmanager
async def telegram_orchestration_uow_factory() -> AsyncIterator[SqlAlchemyOrchestrationUnitOfWork]:
    async with AsyncSessionLocal() as session:
        async with SqlAlchemyOrchestrationUnitOfWork(session) as uow:
            yield uow