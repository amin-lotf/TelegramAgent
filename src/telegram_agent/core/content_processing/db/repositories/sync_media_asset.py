from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.commands import RecordMediaDownloadCommand
from telegram_agent.core.content_processing.db.models.content_processing import MediaAsset


class SyncSqlAlchemyMediaAssetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_single_by_job_id(self, job_id: UUID) -> MediaAsset | None:
        assets = list(self._session.scalars(select(MediaAsset).where(MediaAsset.job_id == job_id)).all())
        return assets[0] if len(assets) == 1 else None

    def record_download(self, command: RecordMediaDownloadCommand) -> bool:
        statement = (
            update(MediaAsset)
            .where(MediaAsset.id == command.media_asset_id, MediaAsset.job_id == command.job_id)
            .values(local_path=command.local_path, size_bytes=command.size_bytes, mime_type=command.mime_type)
            .returning(MediaAsset.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None
