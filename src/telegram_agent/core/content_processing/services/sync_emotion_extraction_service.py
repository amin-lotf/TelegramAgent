from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
import json
import os
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    AudioClipError,
    AudioClipPermanentError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
    SenseVoiceResponseError,
    SenseVoiceServiceError,
)
from telegram_agent.core.content_processing.clients.sensevoice_client import (
    SenseVoiceClient,
)
from telegram_agent.core.content_processing.common.commands import (
    RecordSegmentEmotionsCommand,
    UpdateTranscriptSegmentEmotionCommand,
)
from telegram_agent.core.content_processing.common.results import (
    EmotionExtractionBatchResult,
    EmotionExtractionContext,
    EmotionSegmentInput,
    SegmentEmotionUpdate,
    StageExecutionResult,
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
from telegram_agent.core.content_processing.downloaders.audio_clipper import AudioClipper


class SyncEmotionExtractionService:
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
    def from_settings(cls) -> "SyncEmotionExtractionService":
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
                batch_result = self._extract_emotions(context)
                self._record_success(job_id=job_id, result=batch_result)
                self._cleanup_gpu_inputs(context)
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
            message = "Emotion extraction retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(self, job_id: UUID) -> EmotionExtractionContext | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_emotion_extraction(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            transcript = uow.transcripts.get_by_job_id_with_segments(job_id)
            if transcript is None:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Transcript is missing for emotion extraction",
                )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            segments = tuple(
                EmotionSegmentInput(
                    segment_index=segment.segment_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                )
                for segment in transcript.segments
            )
            if not segments:
                if not uow.jobs.complete_emotion_extraction(job_id=job_id):
                    raise RetryableContentProcessingError(
                        "Empty emotion extraction result could not be applied to job state"
                    )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            asset = uow.media_assets.get_transcription_asset(job_id)
            if asset is None or not asset.local_path:
                uow.jobs.mark_failed(
                    job_id=job_id,
                    error_message="Downloaded media file is missing for emotion extraction",
                )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            # Long media with many segment clips can exceed the initial SLA.
            segment_budget = max(1, len(segments))
            uow.job_expectations.extend_due_at(
                job_id=job_id,
                extra=timedelta(
                    seconds=int(
                        self._settings.sensevoice_request_timeout_seconds * segment_budget
                    )
                    + 120
                ),
            )
            return EmotionExtractionContext(
                job_id=job_id,
                media_asset_id=asset.id,
                local_path=Path(asset.local_path),
                mime_type=asset.mime_type,
                segments=segments,
            )

    def _extract_emotions(
        self,
        context: EmotionExtractionContext,
    ) -> EmotionExtractionBatchResult:
        client = SenseVoiceClient(self._settings)
        clipper = AudioClipper.from_settings(self._settings)
        clip_paths: list[Path] = []
        skipped_indices: list[int] = []
        manifest_path = (
            Path(self._settings.media_storage_root)
            / str(context.job_id)
            / "gpu_inputs"
            / "sensevoice_emotions.json"
        )

        for segment in context.segments:
            if segment.end_ms <= segment.start_ms:
                skipped_indices.append(segment.segment_index)
                continue

            clip_path = clipper.clip_path_for_segment(
                job_id=context.job_id,
                segment_index=segment.segment_index,
            )
            clip_paths.append(clip_path)
            try:
                clipper.extract_clip(
                    source_path=context.local_path,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    dest_path=clip_path,
                )
            except AudioClipPermanentError as exc:
                raise PermanentContentProcessingError(str(exc)) from exc
            except AudioClipError as exc:
                raise RetryableContentProcessingError(str(exc)) from exc

        if not clip_paths:
            return EmotionExtractionBatchResult(
                segments=tuple(
                    SegmentEmotionUpdate(index, None, None)
                    for index in skipped_indices
                )
            )
        self._write_manifest(
            manifest_path=manifest_path,
            context=context,
            clip_paths=clip_paths,
        )
        try:
            batch_result = client.extract_emotions(
                manifest_path=manifest_path,
                request_id=str(context.job_id),
                timeout_seconds=max(
                    1,
                    min(
                        int(
                            self._settings.sensevoice_request_timeout_seconds
                            * max(1, len(clip_paths))
                        ),
                        self._settings.gpu_execution_job_max_timeout_seconds,
                    ),
                ),
                heartbeat=lambda: self._heartbeat(context.job_id),
            )
        except SenseVoiceServiceError as exc:
            raise RetryableContentProcessingError(str(exc)) from exc
        except SenseVoiceResponseError as exc:
            raise PermanentContentProcessingError(str(exc)) from exc
        by_index = {item.segment_index: item for item in batch_result.segments}
        expected_indices = {
            segment.segment_index
            for segment in context.segments
            if segment.segment_index not in skipped_indices
        }
        if set(by_index) != expected_indices:
            raise PermanentContentProcessingError(
                "SenseVoice GPU workload returned an incomplete segment batch"
            )
        return EmotionExtractionBatchResult(
            segments=tuple(
                SegmentEmotionUpdate(index, None, None)
                for index in skipped_indices
            )
            + tuple(by_index[index] for index in sorted(by_index))
        )

    def _cleanup_gpu_inputs(self, context: EmotionExtractionContext) -> None:
        clipper = AudioClipper.from_settings(self._settings)
        paths = [
            clipper.clip_path_for_segment(
                job_id=context.job_id,
                segment_index=segment.segment_index,
            )
            for segment in context.segments
        ]
        paths.append(
            Path(self._settings.media_storage_root)
            / str(context.job_id)
            / "gpu_inputs"
            / "sensevoice_emotions.json"
        )
        for path in paths:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
        for parent in {path.parent for path in paths}:
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                continue

    @staticmethod
    def _write_manifest(
        *,
        manifest_path: Path,
        context: EmotionExtractionContext,
        clip_paths: list[Path],
    ) -> None:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        path_by_index = {
            int(path.stem.split("_")[-1]): path
            for path in clip_paths
        }
        payload = {
            "segments": [
                {
                    "segment_index": segment.segment_index,
                    "path": str(path_by_index[segment.segment_index].resolve()),
                }
                for segment in context.segments
                if segment.segment_index in path_by_index
            ]
        }
        temporary_path = manifest_path.with_name(f".{manifest_path.name}.part")
        temporary_path.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(temporary_path, manifest_path)

    def _heartbeat(self, job_id: UUID) -> None:
        with self._uow_factory() as uow:
            uow.jobs.touch(job_id=job_id)

    def _record_success(
        self,
        *,
        job_id: UUID,
        result: EmotionExtractionBatchResult,
    ) -> None:
        command = RecordSegmentEmotionsCommand(
            job_id=job_id,
            segments=tuple(
                UpdateTranscriptSegmentEmotionCommand(
                    segment_index=segment.segment_index,
                    emotion=segment.emotion,
                    audio_events=segment.audio_events,
                )
                for segment in result.segments
            ),
        )
        with self._uow_factory() as uow:
            if not uow.transcripts.update_segment_emotions(command):
                raise RetryableContentProcessingError(
                    "Emotion extraction result could not be persisted"
                )
            if not uow.jobs.complete_emotion_extraction(job_id=job_id):
                raise RetryableContentProcessingError(
                    "Emotion extraction result could not be applied to job state"
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
                JobStatus.EMOTION_EXTRACTED,
                # Historical terminals from when chunking/embedding were active.
                JobStatus.CHUNKED,
                JobStatus.EMBEDDED,
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
            uow.jobs.mark_emotion_extraction_retryable(
                job_id=job_id,
                error_message=error_message,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            if uow.jobs.mark_failed(job_id=job_id, error_message=error_message):
                uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)
