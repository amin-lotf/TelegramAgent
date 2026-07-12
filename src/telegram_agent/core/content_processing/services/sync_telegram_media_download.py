from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable

from sqlalchemy.exc import SQLAlchemyError
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.commands import RecordMediaDownloadCommand
from telegram_agent.core.content_processing.common.results import (
    StageExecutionResult,
    TelegramDownloadContext,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import OutboxEventType
from telegram_agent.core.content_processing.db.models.content_processing import (
    MediaAsset,
    OutboxEvent,
    TelegramSource,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.downloaders.telegram_media import TelegramMediaDownloader


_TRANSCRIBABLE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.AUDIO.value,
        TelegramAttachmentType.VIDEO.value,
        TelegramAttachmentType.VIDEO_NOTE.value,
        TelegramAttachmentType.VOICE.value,
    }
)


class SyncTelegramMediaDownloadService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork]],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings


    
    
    @classmethod
    def from_settings(cls) -> "SyncTelegramMediaDownloadService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import sync_content_processing_uow_factory

        return cls(uow_factory=sync_content_processing_uow_factory, settings=settings)

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        try:
            context = self._claim_and_resolve(job_id)
            if context is None:
                return StageExecutionResult()
            result = TelegramMediaDownloader.from_settings(self._settings).download(context)
            self._record_success(context=context, result=result)
            return StageExecutionResult()
        except PermanentContentProcessingError as exc:
            self._mark_failed(job_id, str(exc))
            return StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, SQLAlchemyError) as exc:
            return self._retry_or_fail(job_id=job_id, retry_count=retry_count, error_message=str(exc))

    def _retry_or_fail(self, *, job_id: UUID, retry_count: int, error_message: str) -> StageExecutionResult:
        if retry_count >= self._settings.media_task_max_retries:
            self._mark_failed(job_id, "Media download retry limit exhausted")
            return StageExecutionResult(error_message="Media download retry limit exhausted")
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(self, job_id: UUID) -> TelegramDownloadContext | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_download(
                job_id=job_id,
                lease_timeout=timedelta(seconds=self._settings.media_processing_lease_seconds),
            ):
                return None
            asset = uow.media_assets.get_single_by_job_id(job_id)
            sources = uow.telegram_sources.list_by_job_id(job_id)
            error_message = self._source_error(asset=asset, sources=sources)
            if error_message:
                uow.jobs.mark_failed(job_id=job_id, error_message=error_message)
                return None
            assert asset is not None
            source = sources[0]
            return TelegramDownloadContext(
                job_id=job_id,
                media_asset_id=asset.id,
                telegram_file_id=source.telegram_file_id,
                media_type=asset.media_type,
            )

    @staticmethod
    def _source_error(
        *,
        asset: MediaAsset | None,
        sources: list[TelegramSource],
    ) -> str | None:
        if asset is None:
            return "Job must have exactly one media asset"
        if not sources:
            return "No supported source record exists for job"
        if len(sources) != 1:
            return "Job has ambiguous source records"
        source = sources[0]
        if asset.media_type != source.attachment_type.value:
            return "Media asset and source attachment types are inconsistent"
        if not source.telegram_file_id.strip():
            return "Telegram source has no file identifier"
        return None

    def _record_success(self, *, context: TelegramDownloadContext, result) -> None:
        requires_transcription = context.media_type in _TRANSCRIBABLE_ATTACHMENT_TYPES
        with self._uow_factory() as uow:
            if not uow.media_assets.record_download(
                RecordMediaDownloadCommand(
                    job_id=context.job_id,
                    media_asset_id=context.media_asset_id,
                    local_path=result.local_path,
                    size_bytes=result.size_bytes,
                    mime_type=result.mime_type,
                )
            ):
                raise RetryableContentProcessingError("Media asset no longer belongs to job")
            if not uow.jobs.complete_download(
                job_id=context.job_id,
                requires_transcription=requires_transcription,
            ):
                raise RetryableContentProcessingError("Download result could not be applied to job state")
            if requires_transcription:
                event_type = OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION
                event_idempotency_key = f"{event_type.value}:{context.job_id}"
                existing_event = uow.outbox_events.get_by_idempotency_key(
                    event_idempotency_key
                )
                if existing_event is None:
                    uow.outbox_events.add(
                        OutboxEvent(
                        event_type=event_type,
                        job_id=context.job_id,
                        idempotency_key=event_idempotency_key,
                        payload={},
                        )
                    )

    def _mark_retryable(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.jobs.mark_download_retryable(job_id=job_id, error_message=error_message)

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.jobs.mark_failed(job_id=job_id, error_message=error_message)
