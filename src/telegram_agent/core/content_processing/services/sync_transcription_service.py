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
from telegram_agent.core.content_processing.clients.whisperx_client import WhisperXClient
from telegram_agent.core.content_processing.common.commands import (
    RecordTranscriptCommand,
    RecordTranscriptSegmentCommand,
)
from telegram_agent.core.content_processing.common.results import (
    StageExecutionResult,
    TranscriptionContext,
    TranscriptionResult,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


_TRANSCRIBABLE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.AUDIO.value,
        TelegramAttachmentType.VIDEO.value,
        TelegramAttachmentType.VIDEO_NOTE.value,
        TelegramAttachmentType.VOICE.value,
    }
)


class SyncTranscriptionService:
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
    def from_settings(cls) -> "SyncTranscriptionService":
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
                transcription_result = WhisperXClient(self._settings).transcribe(
                    path=context.local_path,
                    mime_type=context.mime_type,
                    request_id=str(context.job_id),
                )
                self._record_success(
                    context=context,
                    result=transcription_result,
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
            message = "Transcription retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(self, job_id: UUID) -> TranscriptionContext | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_transcription(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            asset = uow.media_assets.get_single_by_job_id(job_id)
            if asset is None or asset.media_type not in _TRANSCRIBABLE_ATTACHMENT_TYPES:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Media type is not transcribable",
                )
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None
            if not asset.local_path:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Downloaded media file is missing",
                )
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None
            return TranscriptionContext(
                job_id=job_id,
                media_asset_id=asset.id,
                local_path=Path(asset.local_path),
                mime_type=asset.mime_type,
            )

    def _record_success(
        self,
        *,
        context: TranscriptionContext,
        result: TranscriptionResult,
    ) -> None:
        command = RecordTranscriptCommand(
            job_id=context.job_id,
            text=result.text,
            language=result.language,
            language_probability=result.language_probability,
            duration_ms=result.duration_ms,
            segments=tuple(
                RecordTranscriptSegmentCommand(
                    segment_index=index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    language=segment.language,
                    language_probability=segment.language_probability,
                    speaker=segment.speaker,
                    speaker_confidence=segment.speaker_confidence,
                )
                for index, segment in enumerate(result.segments)
            ),
        )
        with self._uow_factory() as uow:
            if not uow.transcripts.record(command):
                raise RetryableContentProcessingError(
                    "Transcript result could not be persisted"
                )
            if not uow.jobs.complete_transcription(job_id=context.job_id):
                raise RetryableContentProcessingError(
                    "Transcription result could not be applied to job state"
                )

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
            or job.status not in (JobStatus.COMPLETED, JobStatus.FAILED)
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
            uow.jobs.mark_transcription_retryable(
                job_id=job_id,
                error_message=error_message,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.jobs.mark_failed(job_id=job_id, error_message=error_message)
            self._enqueue_terminal_callback_in_uow(uow, job_id)
