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
from telegram_agent.core.content_processing.clients.chunking_client import ChunkingClient
from telegram_agent.core.content_processing.common.commands import (
    RecordContentChunkCommand,
    RecordContentChunksCommand,
)
from telegram_agent.core.content_processing.common.results import (
    ChunkingContext,
    ChunkingResult,
    ChunkingSegmentInput,
    StageExecutionResult,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    ContentChunkType,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


class SyncChunkingService:
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
    def from_settings(cls) -> "SyncChunkingService":
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
                chunking_result = ChunkingClient(self._settings).chunk_transcript(
                    language=context.language,
                    duration_ms=context.duration_ms,
                    segments=context.segments,
                )
                self._record_success(job_id=job_id, result=chunking_result)
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
            message = "Chunking retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(self, job_id: UUID) -> ChunkingContext | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_chunking(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            # Idempotent: chunks already stored (e.g. prior success + retry).
            if uow.content_chunks.count_for_job(
                job_id=job_id,
                content_type=ContentChunkType.TRANSCRIPT,
            ) > 0:
                if not uow.jobs.complete_chunking(job_id=job_id):
                    raise RetryableContentProcessingError(
                        "Existing chunks could not be applied to job state"
                    )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            transcript = uow.transcripts.get_by_job_id_with_segments(job_id)
            if transcript is None:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Transcript is missing for chunking",
                )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            segments = tuple(
                ChunkingSegmentInput(
                    segment_index=segment.segment_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    speaker=segment.speaker,
                    speaker_confidence=segment.speaker_confidence,
                )
                for segment in transcript.segments
            )
            return ChunkingContext(
                job_id=job_id,
                language=transcript.language,
                duration_ms=transcript.duration_ms,
                segments=segments,
            )

    def _record_success(self, *, job_id: UUID, result: ChunkingResult) -> None:
        command = RecordContentChunksCommand(
            job_id=job_id,
            content_type=result.content_type or ContentChunkType.TRANSCRIPT.value,
            chunks=tuple(
                RecordContentChunkCommand(
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    segment_index_start=chunk.segment_index_start,
                    segment_index_end=chunk.segment_index_end,
                    speakers=chunk.speakers,
                    strategy=result.strategy,
                )
                for chunk in result.chunks
            ),
        )
        with self._uow_factory() as uow:
            if not uow.content_chunks.record(command):
                raise RetryableContentProcessingError(
                    "Chunking result could not be persisted"
                )
            if not uow.jobs.complete_chunking(job_id=job_id):
                raise RetryableContentProcessingError(
                    "Chunking result could not be applied to job state"
                )
            uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)

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
            not in (
                JobStatus.CHUNKED,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.TIMED_OUT,
            )
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
            uow.jobs.mark_chunking_retryable(
                job_id=job_id,
                error_message=error_message,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            if uow.jobs.mark_failed(job_id=job_id, error_message=error_message):
                uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)
