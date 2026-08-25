from __future__ import annotations

import json
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    AudioClipError,
    GpuExecutionCanceledError,
    GpuExecutionResponseError,
    GpuExecutionServiceError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
    StorageError,
)
from telegram_agent.core.common.gpu_workloads import (
    COSYVOICE_DUBBING_BATCH_WORKLOAD,
    SAM_AUDIO_RESIDUAL_WORKLOAD,
)
from telegram_agent.core.content_processing.clients.gpu_execution_client import (
    GpuExecutionClient,
)
from telegram_agent.core.content_processing.common.results import StageExecutionResult
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    DubbingStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DubbingWorkflow,
    OutboxEvent,
    TranscriptSegment,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.downloaders.audio_clipper import AudioClipper
from telegram_agent.core.content_processing.downloaders.mux import MuxService
from telegram_agent.core.content_processing.services.dubbing_media import (
    DubbingAudioAssemblyService,
    DubbingSegmentPlanner,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitlePreparationService,
    SubtitleSegment,
)
from telegram_agent.core.content_processing.services.sync_subtitle_translation_service import (
    SyncSubtitleTranslationService,
)
from telegram_agent.core.content_processing.services.subtitle_translation_helpers import (
    languages_match,
)


_PLAN = "dubbing_plan"
_TTS_MANIFEST = "tts_manifest"
_SAM_INPUT = "sam_input"
_RESIDUAL = "residual_audio"
_MIXED = "mixed_audio"
_SUBTITLES = "subtitles"
_FINAL = "final_media"


@dataclass(frozen=True)
class _SourceContext:
    audio_path: Path
    video_path: Path
    source_language: str | None
    segments: list[TranscriptSegment]


class SyncDubbingWorkflowService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [], AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork]
        ],
        settings: Settings,
        translation_service: SyncSubtitleTranslationService | None = None,
        gpu_client: GpuExecutionClient | None = None,
        clipper: AudioClipper | None = None,
        planner: DubbingSegmentPlanner | None = None,
        assembly_service: DubbingAudioAssemblyService | None = None,
        subtitle_service: SubtitlePreparationService | None = None,
        mux_service: MuxService | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._translation = translation_service or SyncSubtitleTranslationService(
            uow_factory=uow_factory, settings=settings, llm_gateway_client=None
        )
        self._gpu = gpu_client or GpuExecutionClient(settings)
        self._clipper = clipper or AudioClipper.from_settings(settings)
        self._planner = planner or DubbingSegmentPlanner()
        self._assembly = assembly_service or DubbingAudioAssemblyService(settings)
        self._subtitles = subtitle_service or SubtitlePreparationService.from_settings(
            settings
        )
        self._mux = mux_service or MuxService.from_settings(settings)
        self._lease = timedelta(seconds=settings.media_processing_lease_seconds)

    @classmethod
    def from_settings(cls) -> "SyncDubbingWorkflowService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
            translation_service=SyncSubtitleTranslationService.from_settings(),
        )

    def start(
        self, *, job_id: UUID, source_job_id: UUID, target_language: str
    ) -> None:
        normalized_language = target_language.strip()
        if not normalized_language:
            raise PermanentContentProcessingError(
                "A target language is required for dubbing"
            )
        with self._uow_factory() as uow:
            existing = uow.dubbing.get_by_job_id(job_id)
            if existing is None:
                workflow = uow.dubbing.add(
                    DubbingWorkflow(
                        job_id=job_id,
                        source_job_id=source_job_id,
                        target_language=normalized_language,
                        status=DubbingStatus.SOURCE_READY,
                        cosyvoice_model=self._settings.cosyvoice_model,
                        sam_model=self._settings.sam_audio_model,
                    )
                )
            else:
                if (
                    existing.source_job_id != source_job_id
                    or existing.target_language.casefold()
                    != normalized_language.casefold()
                ):
                    raise PermanentContentProcessingError(
                        "Dubbing idempotency conflict for source or target language"
                    )
                workflow = existing
            if workflow.status == DubbingStatus.SOURCE_READY:
                self._enqueue(
                    uow,
                    job_id=job_id,
                    event_type=OutboxEventType.DUBBING_SOURCE_RESOLVED,
                )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            status = workflow.status if workflow is not None else None
        if status is None:
            return StageExecutionResult(
                error_message="Dubbing workflow record is missing"
            )
        if status in (
            DubbingStatus.READY_FOR_DELIVERY,
            DubbingStatus.CANCELLED,
            DubbingStatus.FAILED,
        ):
            return StageExecutionResult()
        if status == DubbingStatus.CANCELLING:
            try:
                self._cancel_active_gpu(job_id)
                self._finish_cancellation(job_id)
                return StageExecutionResult()
            except GpuExecutionServiceError as exc:
                if retry_count >= self._settings.media_task_max_retries:
                    self._fail(job_id, f"Unable to cancel GPU workload: {exc}")
                    return StageExecutionResult(error_message=str(exc))
                return StageExecutionResult(retryable=True, error_message=str(exc))
        ready_to_running = {
            DubbingStatus.SOURCE_READY: DubbingStatus.PREPARING_INPUTS,
            DubbingStatus.TTS_READY: DubbingStatus.TTS_RUNNING,
            DubbingStatus.SAM_READY: DubbingStatus.SAM_RUNNING,
            DubbingStatus.ASSEMBLY_READY: DubbingStatus.ASSEMBLING,
        }
        running_to_ready = {running: ready for ready, running in ready_to_running.items()}
        ready = running_to_ready.get(status, status)
        running = ready_to_running.get(ready)
        if running is None:
            self._fail(job_id, f"Unsupported dubbing workflow state: {status.value}")
            return StageExecutionResult(error_message="Unsupported dubbing workflow state")

        try:
            if ready == DubbingStatus.SOURCE_READY:
                claimed = self._claim(job_id, ready, running)
                if not claimed:
                    return self._busy_result()
                self._prepare_inputs(job_id)
            elif ready == DubbingStatus.TTS_READY:
                claimed = self._claim(job_id, ready, running)
                if not claimed:
                    return self._busy_result()
                self._run_tts(job_id)
            elif ready == DubbingStatus.SAM_READY:
                claimed = self._claim(job_id, ready, running)
                if not claimed:
                    return self._busy_result()
                self._run_sam(job_id)
            else:
                claimed = self._claim(job_id, ready, running)
                if not claimed:
                    return self._busy_result()
                self._assemble(job_id)
            return StageExecutionResult()
        except GpuExecutionCanceledError:
            self._finish_cancellation(job_id)
            return StageExecutionResult()
        except (PermanentContentProcessingError, GpuExecutionResponseError) as exc:
            self._fail(job_id, str(exc))
            return StageExecutionResult(error_message=str(exc))
        except (
            RetryableContentProcessingError,
            GpuExecutionServiceError,
            AudioClipError,
            StorageError,
            SQLAlchemyError,
            OSError,
        ) as exc:
            if retry_count >= self._settings.media_task_max_retries:
                message = f"Dubbing stage retry limit exhausted: {exc}"
                self._fail(job_id, message)
                return StageExecutionResult(error_message=message)
            self._reset_for_retry(job_id, running, ready, str(exc))
            return StageExecutionResult(retryable=True, error_message=str(exc))

    def cancel(self, *, job_id: UUID, telegram_user_id: int) -> bool:
        with self._uow_factory() as uow:
            request = uow.download_requests.get_by_job_id(job_id)
            if request is None or request.telegram_user_id != telegram_user_id:
                return False
            workflow = uow.dubbing.request_cancellation(job_id=job_id)
            if workflow is None:
                existing = uow.dubbing.get_by_job_id(job_id)
                return existing is not None and existing.status == DubbingStatus.CANCELLED
            gpu_job_id = workflow.active_gpu_job_id
        if gpu_job_id is not None:
            self._cancel_gpu_job(gpu_job_id)
        self._finish_cancellation(job_id)
        return True

    def _cancel_active_gpu(self, job_id: UUID) -> None:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            gpu_job_id = workflow.active_gpu_job_id if workflow is not None else None
        if gpu_job_id is not None:
            self._cancel_gpu_job(gpu_job_id)

    def _cancel_gpu_job(self, gpu_job_id: UUID) -> None:
        try:
            self._gpu.cancel(gpu_job_id)
        except GpuExecutionServiceError:
            raise
        except GpuExecutionResponseError:
            # A terminal/not-found GPU job does not prevent content cancellation.
            pass

    def _claim(
        self,
        job_id: UUID,
        ready: DubbingStatus,
        running: DubbingStatus,
    ) -> bool:
        with self._uow_factory() as uow:
            return (
                uow.dubbing.claim(
                    job_id=job_id,
                    ready_status=ready,
                    running_status=running,
                    lease_timeout=self._lease,
                )
                is not None
            )

    def _prepare_inputs(self, job_id: UUID) -> None:
        workflow, source = self._load_source(job_id)
        if (
            not self._settings.subtitle_translation_enabled
            and not languages_match(source.source_language, workflow.target_language)
        ):
            raise PermanentContentProcessingError(
                "Subtitle translation must be enabled for cross-language dubbing"
            )
        translated = self._translation.ensure_translated(
            source_job_id=workflow.source_job_id,
            target_language=workflow.target_language,
        )
        planned = self._planner.plan(
            source_segments=source.segments,
            translated_segments=translated,
        )
        job_dir = self._job_dir(job_id)
        prompt_dir = job_dir / "prompt_clips"
        output_dir = job_dir / "tts"
        entries: list[dict[str, object]] = []
        for segment in planned:
            prompt_path = prompt_dir / f"segment_{segment.index:05d}.ogg"
            if not self._valid_file(prompt_path):
                self._clipper.extract_clip(
                    source_path=source.audio_path,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    dest_path=prompt_path,
                )
            entries.append(
                {
                    "index": segment.index,
                    "source_segment_indices": list(segment.source_segment_indices),
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "source_text": segment.source_text,
                    "target_text": segment.target_text,
                    "speaker": segment.speaker,
                    "prompt_path": str(prompt_path),
                }
            )
        plan_path = job_dir / "dubbing_plan.json"
        self._write_json(
            plan_path,
            {
                "job_id": str(job_id),
                "source_job_id": str(workflow.source_job_id),
                "source_language": source.source_language,
                "target_language": workflow.target_language,
                "output_dir": str(output_dir),
                "segments": entries,
            },
        )
        with self._uow_factory() as uow:
            current = uow.dubbing.get_by_job_id(job_id)
            if current is None:
                raise PermanentContentProcessingError("Dubbing workflow disappeared")
            uow.dubbing.upsert_artifact(
                workflow_id=current.id,
                artifact_type=_PLAN,
                local_path=str(plan_path),
                producer="content_processing.dubbing_segment_planner.v1",
                size_bytes=plan_path.stat().st_size,
                metadata={"segment_count": len(entries)},
            )
            if not uow.dubbing.transition(
                job_id=job_id,
                from_status=DubbingStatus.PREPARING_INPUTS,
                to_status=DubbingStatus.TTS_READY,
            ):
                raise RetryableContentProcessingError(
                    "Dubbing input state transition was not applied"
                )
            self._enqueue(
                uow,
                job_id=job_id,
                event_type=OutboxEventType.DUBBING_INPUTS_PREPARED,
            )

    def _run_tts(self, job_id: UUID) -> None:
        workflow, plan_path = self._workflow_and_artifact(job_id, _PLAN)
        result_path = self._job_dir(job_id) / "cosyvoice_result.json"
        gpu_job = self._gpu.submit(
            workload_type=COSYVOICE_DUBBING_BATCH_WORKLOAD,
            idempotency_key=f"dubbing:{job_id}:cosyvoice:v1",
            input_path=plan_path,
            output_path=result_path,
            parameters={
                "model": workflow.cosyvoice_model,
                "inference_mode": self._settings.cosyvoice_inference_mode,
                "prompt_prefix": self._settings.cosyvoice_prompt_prefix,
                "short_text_speed": self._settings.cosyvoice_short_text_speed,
                "short_text_max_attempts": self._settings.cosyvoice_short_text_max_attempts,
                "duration_fit_max_speed": self._settings.cosyvoice_duration_fit_max_speed,
                "duration_fit_target_ratio": self._settings.cosyvoice_duration_fit_target_ratio,
                "max_in_flight_segments": self._settings.cosyvoice_max_in_flight_segments,
            },
            timeout_seconds=self._settings.cosyvoice_request_timeout_seconds,
            max_attempts=self._settings.dubbing_gpu_max_attempts,
        )
        self._record_gpu_job(job_id, DubbingStatus.TTS_RUNNING, gpu_job.id)
        self._gpu.wait(
            job=gpu_job,
            expected_output_path=result_path,
            heartbeat=lambda: self._heartbeat(job_id, DubbingStatus.TTS_RUNNING),
        )
        payload = self._read_json(result_path)
        manifest_path = self._validated_result_path(payload, "manifest_path")
        self._record_gpu_success(
            job_id=job_id,
            from_status=DubbingStatus.TTS_RUNNING,
            to_status=DubbingStatus.SAM_READY,
            artifact_type=_TTS_MANIFEST,
            artifact_path=manifest_path,
            producer=COSYVOICE_DUBBING_BATCH_WORKLOAD,
            event_type=OutboxEventType.DUBBING_SPEECH_SYNTHESIZED,
            metadata={"gpu_job_id": str(gpu_job.id)},
        )

    def _run_sam(self, job_id: UUID) -> None:
        workflow, source = self._load_source(job_id)
        job_dir = self._job_dir(job_id)
        residual_path = job_dir / "residual.wav"
        input_path = job_dir / "sam_input.json"
        result_path = job_dir / "sam_result.json"
        self._write_json(
            input_path,
            {
                "source_audio_path": str(source.audio_path),
                "residual_path": str(residual_path),
            },
        )
        with self._uow_factory() as uow:
            current = uow.dubbing.get_by_job_id(job_id)
            if current is None:
                raise PermanentContentProcessingError("Dubbing workflow disappeared")
            uow.dubbing.upsert_artifact(
                workflow_id=current.id,
                artifact_type=_SAM_INPUT,
                local_path=str(input_path),
                producer="content_processing",
                size_bytes=input_path.stat().st_size,
            )
        gpu_job = self._gpu.submit(
            workload_type=SAM_AUDIO_RESIDUAL_WORKLOAD,
            idempotency_key=f"dubbing:{job_id}:sam-audio:v1",
            input_path=input_path,
            output_path=result_path,
            parameters={
                "model": workflow.sam_model,
                "description": self._settings.sam_audio_description,
                "chunk_seconds": self._settings.sam_audio_chunk_seconds,
                "overlap_seconds": self._settings.sam_audio_overlap_seconds,
            },
            timeout_seconds=self._settings.sam_audio_request_timeout_seconds,
            max_attempts=self._settings.dubbing_gpu_max_attempts,
        )
        self._record_gpu_job(job_id, DubbingStatus.SAM_RUNNING, gpu_job.id)
        self._gpu.wait(
            job=gpu_job,
            expected_output_path=result_path,
            heartbeat=lambda: self._heartbeat(job_id, DubbingStatus.SAM_RUNNING),
        )
        payload = self._read_json(result_path)
        returned_residual = self._validated_result_path(payload, "residual_path")
        if returned_residual != residual_path.resolve():
            raise PermanentContentProcessingError(
                "SAM Audio returned an unexpected residual path"
            )
        self._record_gpu_success(
            job_id=job_id,
            from_status=DubbingStatus.SAM_RUNNING,
            to_status=DubbingStatus.ASSEMBLY_READY,
            artifact_type=_RESIDUAL,
            artifact_path=returned_residual,
            producer=SAM_AUDIO_RESIDUAL_WORKLOAD,
            event_type=OutboxEventType.DUBBING_BACKGROUND_SEPARATED,
            metadata={"gpu_job_id": str(gpu_job.id)},
        )

    def _assemble(self, job_id: UUID) -> None:
        workflow, source = self._load_source(job_id)
        _, plan_path = self._workflow_and_artifact(job_id, _PLAN)
        _, tts_manifest = self._workflow_and_artifact(job_id, _TTS_MANIFEST)
        _, residual = self._workflow_and_artifact(job_id, _RESIDUAL)
        mixed = self._assembly.assemble(
            job_id=job_id,
            video_path=source.video_path,
            residual_path=residual,
            plan_path=plan_path,
            tts_manifest_path=tts_manifest,
        )
        with self._uow_factory() as uow:
            request = uow.download_requests.get_by_job_id(job_id)
            if request is None:
                raise PermanentContentProcessingError("Download request is missing")
            subtitle_language = (
                request.requested_subtitle_language or workflow.target_language
            )
        subtitle_segments = self._translation.ensure_translated(
            source_job_id=workflow.source_job_id,
            target_language=subtitle_language,
        )
        subtitle_path = Path(
            self._subtitles.prepare(
                job_id=job_id,
                segments=subtitle_segments,
                target_language=subtitle_language,
            )
        )
        final_path = Path(
            self._mux.mux(
                job_id=job_id,
                video_path=str(source.video_path),
                audio_path=str(mixed),
                subtitle_path=str(subtitle_path),
                subtitle_language=subtitle_language,
                subtitle_title=subtitle_language,
                audio_language=workflow.target_language,
                audio_bitrate=self._settings.dubbing_audio_bitrate,
            )
        )
        with self._uow_factory() as uow:
            current = uow.dubbing.get_by_job_id(job_id)
            if current is None:
                raise PermanentContentProcessingError("Dubbing workflow disappeared")
            for artifact_type, path, producer in (
                (_MIXED, mixed, "content_processing.dub_audio_assembly.v1"),
                (_SUBTITLES, subtitle_path, "content_processing.subtitle_preparation"),
                (_FINAL, final_path, "content_processing.mux"),
            ):
                uow.dubbing.upsert_artifact(
                    workflow_id=current.id,
                    artifact_type=artifact_type,
                    local_path=str(path),
                    producer=producer,
                    size_bytes=path.stat().st_size,
                )
            if not uow.download_requests.set_final_path(
                job_id=job_id, final_path=str(final_path)
            ):
                raise RetryableContentProcessingError("Unable to persist dubbed media")
            if not uow.dubbing.transition(
                job_id=job_id,
                from_status=DubbingStatus.ASSEMBLING,
                to_status=DubbingStatus.READY_FOR_DELIVERY,
            ):
                raise RetryableContentProcessingError(
                    "Dubbing completion state was not applied"
                )
            if not uow.jobs.complete_download(
                job_id=job_id, requires_transcription=False
            ):
                raise RetryableContentProcessingError(
                    "Dubbing job completion was not applied"
                )
            uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue(
                uow,
                job_id=job_id,
                event_type=OutboxEventType.DOWNLOAD_READY_FOR_DELIVERY,
            )

    def _load_source(self, job_id: UUID) -> tuple[DubbingWorkflow, _SourceContext]:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            if workflow is None:
                raise PermanentContentProcessingError("Dubbing workflow is missing")
            audio = uow.media_assets.get_by_job_id_and_role(
                workflow.source_job_id, MediaAssetRole.AUDIO
            )
            video = uow.media_assets.get_by_job_id_and_role(
                workflow.source_job_id, MediaAssetRole.VIDEO
            )
            transcript = uow.transcripts.get_by_job_id_with_segments(
                workflow.source_job_id
            )
            if (
                audio is None
                or not audio.local_path
                or video is None
                or not video.local_path
                or transcript is None
                or not transcript.segments
            ):
                raise PermanentContentProcessingError(
                    "Dubbing source assets or transcript are missing"
                )
            segments = [
                TranscriptSegment(
                    id=item.id,
                    transcript_id=item.transcript_id,
                    segment_index=item.segment_index,
                    start_ms=item.start_ms,
                    end_ms=item.end_ms,
                    text=item.text,
                    language=item.language,
                    language_probability=item.language_probability,
                    speaker=item.speaker,
                    speaker_confidence=item.speaker_confidence,
                )
                for item in transcript.segments
            ]
            detached = DubbingWorkflow(
                id=workflow.id,
                job_id=workflow.job_id,
                source_job_id=workflow.source_job_id,
                target_language=workflow.target_language,
                status=workflow.status,
                active_gpu_job_id=workflow.active_gpu_job_id,
                cosyvoice_model=workflow.cosyvoice_model,
                sam_model=workflow.sam_model,
            )
            return detached, _SourceContext(
                audio_path=Path(audio.local_path),
                video_path=Path(video.local_path),
                source_language=transcript.language,
                segments=segments,
            )

    def _workflow_and_artifact(
        self, job_id: UUID, artifact_type: str
    ) -> tuple[DubbingWorkflow, Path]:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            if workflow is None:
                raise PermanentContentProcessingError("Dubbing workflow is missing")
            artifact = uow.dubbing.get_artifact(
                workflow_id=workflow.id, artifact_type=artifact_type
            )
            if artifact is None:
                raise PermanentContentProcessingError(
                    f"Dubbing artifact is missing: {artifact_type}"
                )
            path = Path(artifact.local_path)
            if not self._valid_file(path):
                raise PermanentContentProcessingError(
                    f"Dubbing artifact file is invalid: {artifact_type}"
                )
            detached = DubbingWorkflow(
                id=workflow.id,
                job_id=workflow.job_id,
                source_job_id=workflow.source_job_id,
                target_language=workflow.target_language,
                status=workflow.status,
                active_gpu_job_id=workflow.active_gpu_job_id,
                cosyvoice_model=workflow.cosyvoice_model,
                sam_model=workflow.sam_model,
            )
            return detached, path

    def _record_gpu_job(
        self, job_id: UUID, status: DubbingStatus, gpu_job_id: UUID
    ) -> None:
        with self._uow_factory() as uow:
            if not uow.dubbing.set_active_gpu_job(
                job_id=job_id, running_status=status, gpu_job_id=gpu_job_id
            ):
                raise GpuExecutionCanceledError(
                    "Dubbing workflow was cancelled during GPU submission"
                )

    def _record_gpu_success(
        self,
        *,
        job_id: UUID,
        from_status: DubbingStatus,
        to_status: DubbingStatus,
        artifact_type: str,
        artifact_path: Path,
        producer: str,
        event_type: OutboxEventType,
        metadata: dict[str, object],
    ) -> None:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            if workflow is None:
                raise PermanentContentProcessingError("Dubbing workflow disappeared")
            uow.dubbing.upsert_artifact(
                workflow_id=workflow.id,
                artifact_type=artifact_type,
                local_path=str(artifact_path),
                producer=producer,
                size_bytes=artifact_path.stat().st_size,
                metadata=metadata,
            )
            if not uow.dubbing.transition(
                job_id=job_id,
                from_status=from_status,
                to_status=to_status,
                clear_gpu_job=True,
            ):
                raise GpuExecutionCanceledError(
                    "Dubbing workflow was cancelled while GPU work completed"
                )
            self._enqueue(uow, job_id=job_id, event_type=event_type)

    def _heartbeat(self, job_id: UUID, status: DubbingStatus) -> None:
        with self._uow_factory() as uow:
            if not uow.dubbing.touch(job_id=job_id, status=status):
                raise GpuExecutionCanceledError("Dubbing workflow is no longer active")
            uow.jobs.touch(job_id=job_id)

    def _reset_for_retry(
        self,
        job_id: UUID,
        running: DubbingStatus,
        ready: DubbingStatus,
        error_message: str,
    ) -> None:
        with self._uow_factory() as uow:
            uow.dubbing.mark_retryable(
                job_id=job_id,
                from_status=running,
                to_status=ready,
                error_message=error_message,
            )
            uow.jobs.touch(job_id=job_id)

    def _fail(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.dubbing.mark_failed(job_id=job_id, error_message=error_message)
            uow.jobs.mark_failed(job_id=job_id, error_message=error_message)
            uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue(
                uow,
                job_id=job_id,
                event_type=OutboxEventType.DOWNLOAD_FAILED_FOR_DELIVERY,
            )

    def _finish_cancellation(self, job_id: UUID) -> None:
        with self._uow_factory() as uow:
            workflow = uow.dubbing.get_by_job_id(job_id)
            if workflow is None:
                return
            if workflow.status == DubbingStatus.CANCELLING:
                uow.dubbing.mark_cancelled(job_id=job_id)
                uow.jobs.mark_cancelled(
                    job_id=job_id, error_message="Dubbing request was cancelled"
                )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue(
                    uow,
                    job_id=job_id,
                    event_type=OutboxEventType.DOWNLOAD_FAILED_FOR_DELIVERY,
                )

    @staticmethod
    def _enqueue(
        uow: SyncSqlAlchemyContentProcessingUnitOfWork,
        *,
        job_id: UUID,
        event_type: OutboxEventType,
    ) -> None:
        key = f"{event_type.value}:{job_id}"
        if uow.outbox_events.get_by_idempotency_key(key) is None:
            uow.outbox_events.add(
                OutboxEvent(
                    event_type=event_type,
                    job_id=job_id,
                    idempotency_key=key,
                    payload={},
                )
            )

    def _job_dir(self, job_id: UUID) -> Path:
        root = Path(self._settings.media_storage_root).expanduser().resolve()
        path = (root / str(job_id) / "dubbing").resolve()
        if not path.is_relative_to(root):
            raise StorageError("Dubbing job path escaped media storage")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _validated_result_path(
        self, payload: dict[str, object], field_name: str
    ) -> Path:
        path = Path(str(payload.get(field_name) or "")).resolve()
        root = Path(self._settings.media_storage_root).expanduser().resolve()
        if not path.is_relative_to(root) or not self._valid_file(path):
            raise PermanentContentProcessingError(
                f"GPU result contains invalid {field_name}"
            )
        return path

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.part")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermanentContentProcessingError("GPU result JSON is invalid") from exc
        if not isinstance(payload, dict):
            raise PermanentContentProcessingError("GPU result must be an object")
        return payload

    @staticmethod
    def _valid_file(path: Path) -> bool:
        try:
            return path.is_file() and not path.is_symlink() and path.stat().st_size > 0
        except OSError:
            return False

    @staticmethod
    def _busy_result() -> StageExecutionResult:
        return StageExecutionResult(
            deferred=True,
            error_message="Dubbing stage could not acquire its persisted lease",
        )
