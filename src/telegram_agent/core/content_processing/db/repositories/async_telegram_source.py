from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.models.content_processing import TelegramSource


class AsyncSqlAlchemyTelegramSourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, source:TelegramSource) -> TelegramSource:
        self._session.add(source)
        await self._session.flush()
        return source

    async def get_by_id(self, source_id: UUID) -> TelegramSource | None:
        stmt = select(TelegramSource).where(TelegramSource.id == source_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(
        self,
        source_id: UUID,
        **fields,
    ) -> TelegramSource | None:
        source = await self.get_by_id(source_id)

        if source is None:
            return None

        for key, value in fields.items():
            setattr(source, key, value)

        await self._session.flush()
        return source