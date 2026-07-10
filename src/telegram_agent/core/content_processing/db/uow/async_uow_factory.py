from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from telegram_agent.core.content_processing.db.async_session import AsyncSessionLocal
from telegram_agent.core.content_processing.db.uow.async_content_processing import \
    AsyncSqlAlchemyContentProcessingUnitOfWork


@asynccontextmanager
async def async_content_processing_uow_factory() -> AsyncIterator[AsyncSqlAlchemyContentProcessingUnitOfWork]:
    async with AsyncSessionLocal() as session:
        async with AsyncSqlAlchemyContentProcessingUnitOfWork(session) as uow:
            yield uow