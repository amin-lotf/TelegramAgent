from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.results import StageExecutionResult
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    DownloadMediaType,
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    OutboxEvent,
    TelegramSource,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.downloaders.mux import MuxService
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitlePreparationService,
)

_VIDEO_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VIDEO.value,
        TelegramAttachmentType.VIDEO_NOTE.value,
    }
)
_AUDIO_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.AUDIO.value,
        TelegramAttachmentType.VOICE.value,
    }
)
_DOCUMENT_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.DOCUMENT.value,
    }
)


class SyncDownloadPreparationService:
    """Orchestrate plain download preparation (no translation/dubbing yet).

    Extension points:
    - ``requested_subtitle_language`` / transcript language: later feed a translator
      before SubtitlePreparationService.
    - ``requested_dub_language``: later produce a dub track and pass it as
      MuxService ``audio_path`` instead of the original audio asset.
    - ``requested_format`` / ``requested_language``: later convert audio/document.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
        subtitle_service: SubtitlePreparationService | None = None,
        mux_service: MuxService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._subtitle_service = subtitle_service or SubtitlePreparationService.from_settings(
            settings
        )
        self._mux_service = mux_service or MuxService.from_settings(settings)

    @classmethod
    def from_settings(cls) -> "SyncDownloadPreparationService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
        )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        try:
            download_request = self._claim_and_load(job_id)
            if download_request is None:
                return StageExecutionResult()

            final_path = self._prepare(download_request)
            self._record_success(job_id=job_id, final_path=final_path)
            return StageExecutionResult()
        except PermanentContentProcessingError as exc:
            self._mark_failed(job_id, str(exc))
            return StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, SQLAlchemyError) as exc:
            return self._retry_or_fail(
                job_id=job_id,
                retry_count=retry_count,
                error_message=str(exc),
            )

    def _claim_and_load(self, job_id: UUID) -> DownloadRequest | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_download(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            request = uow.download_requests.get_by_job_id(job_id)
            if request is None:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Download request record is missing",
                )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                return None

            # Detach attributes needed outside the session.
            return DownloadRequest(
                id=request.id,
                job_id=request.job_id,
                chat_id=request.chat_id,
                telegram_user_id=request.telegram_user_id,
                group_id=request.group_id,
                agent_message_id=request.agent_message_id,
                media_ingress_message_id=request.media_ingress_message_id,
                media_type=request.media_type,
                requested_subtitle_language=request.requested_subtitle_language,
                requested_dub_language=request.requested_dub_language,
                requested_language=request.requested_language,
                requested_format=request.requested_format,
                assistant_text=request.assistant_text,
                final_path=request.final_path,
            )

    def _prepare(self, request: DownloadRequest) -> str:
        source_job_id = self._resolve_source_job_id(request)
        media_type = request.media_type

        if media_type == DownloadMediaType.VIDEO.value:
            return self._prepare_video(request=request, source_job_id=source_job_id)
        if media_type == DownloadMediaType.AUDIO.value:
            return self._prepare_audio(source_job_id=source_job_id, request=request)
        if media_type == DownloadMediaType.DOCUMENT.value:
            return self._prepare_document(source_job_id=source_job_id, request=request)
        raise PermanentContentProcessingError(
            f"Unsupported download media_type: {media_type}"
        )

    def _resolve_source_job_id(self, request: DownloadRequest) -> UUID:
        """Resolve the original attachment job, waiting while it is still processing.

        Agent-runtime often hands off the download request while content-processing
        is still downloading/transcribing the original media. That is a temporary
        condition and must be retryable — not a permanent failure.
        """
        _IN_PROGRESS = frozenset(
            {
                JobStatus.QUEUED,
                JobStatus.RUNNING,
                JobStatus.DOWNLOADED,
                JobStatus.TRANSCRIBING,
            }
        )
        _TERMINAL_FAILURE = frozenset(
            {
                JobStatus.FAILED,
                JobStatus.TIMED_OUT,
                JobStatus.CANCELLED,
            }
        )

        with self._uow_factory() as uow:
            sources = uow.telegram_sources.list_by_ingress_message_id(
                request.media_ingress_message_id
            )
            if not sources:
                # Source row may not be visible yet if attachment accept races handoff.
                raise RetryableContentProcessingError(
                    "Source media not found yet for media_ingress_message_id; "
                    "waiting for ingestion"
                )

            matching = [
                source
                for source in sources
                if self._source_matches_media_type(source, request.media_type)
            ]
            candidates = matching or sources

            saw_in_progress = False
            saw_terminal_failure = False

            for source in candidates:
                job = uow.jobs.get_by_id(source.job_id)
                if job is None:
                    continue

                if job.status in _TERMINAL_FAILURE:
                    saw_terminal_failure = True
                    continue

                if job.status in _IN_PROGRESS:
                    saw_in_progress = True
                    continue

                if job.status != JobStatus.COMPLETED:
                    saw_in_progress = True
                    continue

                if request.media_type == DownloadMediaType.VIDEO.value:
                    transcript = uow.transcripts.get_by_job_id(source.job_id)
                    if transcript is None:
                        # Completed without transcript is unexpected for video; wait
                        # briefly in case of commit ordering, then exhaust retries.
                        saw_in_progress = True
                        continue
                    video_asset = uow.media_assets.get_by_job_id_and_role(
                        source.job_id, MediaAssetRole.VIDEO
                    )
                    audio_asset = uow.media_assets.get_by_job_id_and_role(
                        source.job_id, MediaAssetRole.AUDIO
                    )
                    if (
                        video_asset is None
                        or not video_asset.local_path
                        or audio_asset is None
                        or not audio_asset.local_path
                    ):
                        saw_in_progress = True
                        continue
                else:
                    source_asset = uow.media_assets.get_source_by_job_id(source.job_id)
                    if source_asset is None or not source_asset.local_path:
                        saw_in_progress = True
                        continue

                return source.job_id

            if saw_in_progress:
                raise RetryableContentProcessingError(
                    "Source media is still processing (download/transcription); "
                    "waiting until ready"
                )
            if saw_terminal_failure:
                raise PermanentContentProcessingError(
                    "Source media job failed before download preparation could run"
                )
            raise PermanentContentProcessingError(
                "No usable source job found for download preparation"
            )

    @staticmethod
    def _source_matches_media_type(source: TelegramSource, media_type: str) -> bool:
        attachment = source.attachment_type.value
        if media_type == DownloadMediaType.VIDEO.value:
            return attachment in _VIDEO_ATTACHMENT_TYPES
        if media_type == DownloadMediaType.AUDIO.value:
            return attachment in _AUDIO_ATTACHMENT_TYPES
        if media_type == DownloadMediaType.DOCUMENT.value:
            return attachment in _DOCUMENT_ATTACHMENT_TYPES
        return False

    def _prepare_video(self, *, request: DownloadRequest, source_job_id: UUID) -> str:
        with self._uow_factory() as uow:
            video_asset = uow.media_assets.get_by_job_id_and_role(
                source_job_id, MediaAssetRole.VIDEO
            )
            audio_asset = uow.media_assets.get_by_job_id_and_role(
                source_job_id, MediaAssetRole.AUDIO
            )
            transcript = uow.transcripts.get_by_job_id_with_segments(source_job_id)

            if video_asset is None or not video_asset.local_path:
                raise PermanentContentProcessingError(
                    "Source video asset is missing for download preparation"
                )
            if audio_asset is None or not audio_asset.local_path:
                raise PermanentContentProcessingError(
                    "Source audio asset is missing for download preparation"
                )
            if transcript is None:
                raise PermanentContentProcessingError(
                    "Source transcript is missing for download preparation"
                )
            if not transcript.segments:
                raise PermanentContentProcessingError(
                    "Source transcript has no segments"
                )

            video_path = video_asset.local_path
            audio_path = audio_asset.local_path
            # Extension point: requested_dub_language would replace audio_path.
            _ = request.requested_dub_language
            subtitle_language = (
                request.requested_subtitle_language or transcript.language
            )
            segments = list(transcript.segments)

        subtitle_path = self._subtitle_service.prepare(
            job_id=request.job_id,
            segments=segments,
            target_language=subtitle_language,
        )
        return self._mux_service.mux(
            job_id=request.job_id,
            video_path=video_path,
            audio_path=audio_path,
            subtitle_path=subtitle_path,
        )

    def _prepare_audio(
        self,
        *,
        source_job_id: UUID,
        request: DownloadRequest,
    ) -> str:
        # Extension point: requested_language may drive future translation/TTS.
        _ = request.requested_language
        with self._uow_factory() as uow:
            audio = uow.media_assets.get_by_job_id_and_role(
                source_job_id, MediaAssetRole.AUDIO
            )
            source = uow.media_assets.get_source_by_job_id(source_job_id)
            asset = audio if audio is not None and audio.local_path else source
            if asset is None or not asset.local_path:
                raise PermanentContentProcessingError(
                    "Source audio file is missing for download preparation"
                )
            if not Path(asset.local_path).is_file():
                raise PermanentContentProcessingError(
                    "Source audio file path does not exist"
                )
            return asset.local_path

    def _prepare_document(
        self,
        *,
        source_job_id: UUID,
        request: DownloadRequest,
    ) -> str:
        # Extension point: requested_format may drive future conversion.
        _ = request.requested_format
        with self._uow_factory() as uow:
            source = uow.media_assets.get_source_by_job_id(source_job_id)
            if source is None or not source.local_path:
                raise PermanentContentProcessingError(
                    "Source document file is missing for download preparation"
                )
            if not Path(source.local_path).is_file():
                raise PermanentContentProcessingError(
                    "Source document file path does not exist"
                )
            return source.local_path

    def _record_success(self, *, job_id: UUID, final_path: str) -> None:
        with self._uow_factory() as uow:
            if not uow.download_requests.set_final_path(
                job_id=job_id,
                final_path=final_path,
            ):
                raise RetryableContentProcessingError(
                    "Download request could not be updated with final path"
                )
            if not uow.jobs.complete_download(
                job_id=job_id,
                requires_transcription=False,
            ):
                raise RetryableContentProcessingError(
                    "Download preparation result could not be applied to job state"
                )
            uow.job_expectations.mark_satisfied(job_id=job_id)

            event_type = OutboxEventType.DOWNLOAD_READY_FOR_DELIVERY
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

    def _retry_or_fail(
        self,
        *,
        job_id: UUID,
        retry_count: int,
        error_message: str,
    ) -> StageExecutionResult:
        # Allow a longer retry budget when waiting for the source attachment job.
        waiting_for_source = "waiting" in error_message.lower()
        max_retries = (
            36 if waiting_for_source else self._settings.media_task_max_retries
        )
        if retry_count >= max_retries:
            message = "Download preparation retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

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
