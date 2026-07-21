from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.commands import (
    RecordMediaDownloadCommand,
    UpsertDerivedMediaAssetCommand,
)
from telegram_agent.core.content_processing.common.results import (
    MediaDemuxResult,
    MediaDownloadResult,
    StageExecutionResult,
    TelegramDownloadContext,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    MediaAsset,
    OutboxEvent,
    TelegramSource,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.downloaders.media_container import (
    path_looks_like_audio,
    path_looks_like_video,
)
from telegram_agent.core.content_processing.downloaders.media_demuxer import MediaDemuxer
from telegram_agent.core.content_processing.downloaders.telegram_media import (
    TelegramMediaDownloader,
)


_TRANSCRIBABLE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.AUDIO.value,
        TelegramAttachmentType.VIDEO.value,
        TelegramAttachmentType.VIDEO_NOTE.value,
        TelegramAttachmentType.VOICE.value,
    }
)

_DEMUX_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VIDEO.value,
        TelegramAttachmentType.VIDEO_NOTE.value,
    }
)

# Telegram often sends MKV/large video as ``document``. Those still need demux
# + transcription so download/translation can build subtitled outputs.
_DOCUMENT_ATTACHMENT_TYPE = TelegramAttachmentType.DOCUMENT.value


class SyncTelegramMediaDownloadService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    @classmethod
    def from_settings(cls) -> "SyncTelegramMediaDownloadService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
        )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        try:
            context = self._claim_and_resolve(job_id)
            if context is None:
                result = StageExecutionResult()
            else:
                download_result = TelegramMediaDownloader.from_settings(
                    self._settings
                ).download(context)
                demux_result: MediaDemuxResult | None = None
                if self._should_demux(
                    media_type=context.media_type,
                    local_path=download_result.local_path,
                ):
                    demux_result = MediaDemuxer.from_settings(self._settings).demux(
                        job_id=context.job_id,
                        source_asset_id=context.media_asset_id,
                        source_path=download_result.local_path,
                    )
                self._record_success(
                    context=context,
                    download_result=download_result,
                    demux_result=demux_result,
                )
                result = StageExecutionResult()
        except PermanentContentProcessingError as exc:
            self._mark_failed(job_id, str(exc))
            result = StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, SQLAlchemyError) as exc:
            result = self._retry_or_fail(
                job_id=job_id,
                retry_count=retry_count,
                error_message=str(exc),
            )

        self._enqueue_terminal_callback(job_id)
        return result

    def _retry_or_fail(
        self,
        *,
        job_id: UUID,
        retry_count: int,
        error_message: str,
    ) -> StageExecutionResult:
        if retry_count >= self._settings.media_task_max_retries:
            message = "Media download retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(self, job_id: UUID) -> TelegramDownloadContext | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_download(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            asset = uow.media_assets.get_source_by_job_id(job_id)
            sources = uow.telegram_sources.list_by_job_id(job_id)
            error_message = self._source_error(asset=asset, sources=sources)
            if error_message:
                uow.jobs.mark_failed(job_id=job_id, error_message=error_message)
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
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
            return "Job must have exactly one source media asset"
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

    @staticmethod
    def _should_demux(*, media_type: str, local_path: str) -> bool:
        if media_type in _DEMUX_ATTACHMENT_TYPES:
            return True
        if media_type == _DOCUMENT_ATTACHMENT_TYPE:
            return path_looks_like_video(local_path)
        return False

    @staticmethod
    def _requires_transcription(
        *,
        media_type: str,
        local_path: str,
        demux_result: MediaDemuxResult | None,
    ) -> bool:
        if media_type in _TRANSCRIBABLE_ATTACHMENT_TYPES:
            return True
        if demux_result is not None:
            return True
        if media_type == _DOCUMENT_ATTACHMENT_TYPE:
            return path_looks_like_audio(local_path)
        return False

    def _record_success(
        self,
        *,
        context: TelegramDownloadContext,
        download_result: MediaDownloadResult,
        demux_result: MediaDemuxResult | None,
    ) -> None:
        requires_transcription = self._requires_transcription(
            media_type=context.media_type,
            local_path=download_result.local_path,
            demux_result=demux_result,
        )
        with self._uow_factory() as uow:
            if not uow.media_assets.record_download(
                RecordMediaDownloadCommand(
                    job_id=context.job_id,
                    media_asset_id=context.media_asset_id,
                    local_path=download_result.local_path,
                    size_bytes=download_result.size_bytes,
                    mime_type=download_result.mime_type,
                )
            ):
                raise RetryableContentProcessingError(
                    "Media asset no longer belongs to job"
                )

            if demux_result is not None:
                uow.media_assets.upsert_derived_asset(
                    UpsertDerivedMediaAssetCommand(
                        job_id=context.job_id,
                        role=MediaAssetRole.AUDIO.value,
                        media_type=context.media_type,
                        parent_asset_id=context.media_asset_id,
                        local_path=demux_result.audio_path,
                        size_bytes=demux_result.audio_size_bytes,
                        mime_type=demux_result.audio_mime_type,
                    )
                )
                uow.media_assets.upsert_derived_asset(
                    UpsertDerivedMediaAssetCommand(
                        job_id=context.job_id,
                        role=MediaAssetRole.VIDEO.value,
                        media_type=context.media_type,
                        parent_asset_id=context.media_asset_id,
                        local_path=demux_result.video_path,
                        size_bytes=demux_result.video_size_bytes,
                        mime_type=demux_result.video_mime_type,
                    )
                )

            if not uow.jobs.complete_download(
                job_id=context.job_id,
                requires_transcription=requires_transcription,
            ):
                raise RetryableContentProcessingError(
                    "Download result could not be applied to job state"
                )
            if requires_transcription:
                event_type = OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION
                idempotency_key = f"{event_type.value}:{context.job_id}"
                if uow.outbox_events.get_by_idempotency_key(idempotency_key) is None:
                    uow.outbox_events.add(
                        OutboxEvent(
                            event_type=event_type,
                            job_id=context.job_id,
                            idempotency_key=idempotency_key,
                            payload={},
                        )
                    )
            else:
                uow.job_expectations.mark_satisfied(job_id=context.job_id)
            self._enqueue_terminal_callback_in_uow(uow, context.job_id)

    def _enqueue_terminal_callback(self, job_id: UUID) -> None:
        with self._uow_factory() as uow:
            self._enqueue_terminal_callback_in_uow(uow, job_id)

    @staticmethod
    def _enqueue_terminal_callback_in_uow(
        uow: SyncSqlAlchemyContentProcessingUnitOfWork,
        job_id: UUID,
    ) -> None:
        job = uow.jobs.get_by_id(job_id)
        if (
            job is None
            or not job.callback_required
            or job.status
            not in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.TIMED_OUT)
        ):
            return

        event_type = OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED
        idempotency_key = f"{event_type.value}:{job_id}"
        if uow.outbox_events.get_by_idempotency_key(idempotency_key) is None:
            uow.outbox_events.add(
                OutboxEvent(
                    event_type=event_type,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    payload={},
                )
            )

    def _mark_retryable(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.jobs.mark_download_retryable(
                job_id=job_id,
                error_message=error_message,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            if uow.jobs.mark_failed(job_id=job_id, error_message=error_message):
                uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)
