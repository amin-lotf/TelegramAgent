from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telegram_agent.core.agent_runtime.db.async_session import AsyncSessionLocal
from telegram_agent.core.agent_runtime.db.uow.async_agent_runtime import (
    AsyncSqlAlchemyAgentRuntimeUnitOfWork,
)


@asynccontextmanager
async def async_agent_runtime_uow_factory() -> AsyncIterator[
    AsyncSqlAlchemyAgentRuntimeUnitOfWork
]:
    async with AsyncSessionLocal() as session:
        async with AsyncSqlAlchemyAgentRuntimeUnitOfWork(session) as uow:
            yield uow



