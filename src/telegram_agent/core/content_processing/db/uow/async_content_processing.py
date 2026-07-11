from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.repositories.async_job import AsyncSqlAlchemyJobRepository
from telegram_agent.core.content_processing.db.repositories.async_media_asset import AsyncSqlAlchemyMediaAssetRepository
from telegram_agent.core.content_processing.db.repositories.async_telegram_source import \
    AsyncSqlAlchemyTelegramSourceRepository


class AsyncSqlAlchemyContentProcessingUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.jobs = AsyncSqlAlchemyJobRepository(session)
        self.telegram_sources = AsyncSqlAlchemyTelegramSourceRepository(session)
        self.media_assets = AsyncSqlAlchemyMediaAssetRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def flush(self) -> None:
        await self._session.flush()

    async def __aenter__(self) -> "AsyncSqlAlchemyContentProcessingUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
