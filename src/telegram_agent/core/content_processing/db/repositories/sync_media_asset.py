from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.commands import (
    RecordMediaDownloadCommand,
    UpsertDerivedMediaAssetCommand,
)
from telegram_agent.core.content_processing.common.types import MediaAssetRole
from telegram_agent.core.content_processing.db.models.content_processing import MediaAsset


class SyncSqlAlchemyMediaAssetRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, asset: MediaAsset) -> MediaAsset:
        self._session.add(asset)
        self._session.flush()
        return asset

    def get_by_job_id_and_role(
        self,
        job_id: UUID,
        role: MediaAssetRole,
    ) -> MediaAsset | None:
        return self._session.scalar(
            select(MediaAsset).where(
                MediaAsset.job_id == job_id,
                MediaAsset.role == role,
            )
        )

    def list_by_job_id(self, job_id: UUID) -> list[MediaAsset]:
        return list(
            self._session.scalars(
                select(MediaAsset).where(MediaAsset.job_id == job_id)
            ).all()
        )

    def get_source_by_job_id(self, job_id: UUID) -> MediaAsset | None:
        return self.get_by_job_id_and_role(job_id, MediaAssetRole.SOURCE)

    def get_transcription_asset(self, job_id: UUID) -> MediaAsset | None:
        audio = self.get_by_job_id_and_role(job_id, MediaAssetRole.AUDIO)
        if audio is not None:
            return audio
        return self.get_source_by_job_id(job_id)

    def record_download(self, command: RecordMediaDownloadCommand) -> bool:
        statement = (
            update(MediaAsset)
            .where(
                MediaAsset.id == command.media_asset_id,
                MediaAsset.job_id == command.job_id,
            )
            .values(
                local_path=command.local_path,
                size_bytes=command.size_bytes,
                mime_type=command.mime_type,
            )
            .returning(MediaAsset.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def upsert_derived_asset(self, command: UpsertDerivedMediaAssetCommand) -> MediaAsset:
        existing = self.get_by_job_id_and_role(
            command.job_id,
            MediaAssetRole(command.role),
        )
        if existing is not None:
            existing.local_path = command.local_path
            existing.size_bytes = command.size_bytes
            existing.mime_type = command.mime_type
            existing.media_type = command.media_type
            existing.parent_asset_id = command.parent_asset_id
            self._session.flush()
            return existing

        asset = MediaAsset(
            job_id=command.job_id,
            role=MediaAssetRole(command.role),
            parent_asset_id=command.parent_asset_id,
            local_path=command.local_path,
            media_type=command.media_type,
            mime_type=command.mime_type,
            duration_ms=None,
            size_bytes=command.size_bytes,
        )
        return self.add(asset)
