from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.db.models.content_processing import MediaAsset


class AsyncSqlAlchemyMediaAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, asset:MediaAsset) -> MediaAsset:
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def get_by_id(self, asset_id: UUID) -> MediaAsset | None:
        stmt = select(MediaAsset).where(MediaAsset.id == asset_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_fields(
        self,
        asset_id: UUID,
        **fields,
    ) -> MediaAsset | None:
        asset = await self.get_by_id(asset_id)

        if asset is None:
            return None

        for key, value in fields.items():
            setattr(asset, key, value)

        await self._session.flush()
        return asset