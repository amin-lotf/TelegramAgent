from __future__ import annotations

import asyncio
import importlib
import logging
import threading
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from telegram_agent.core.common.exceptions import WhisperXBackendBusyError, WhisperXBackendUnavailableError
from telegram_agent.core.whisperx.common.const import (
    DEFAULT_WHISPERX_MERGE_SAME_SPEAKER_ONLY,
    DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
    DEFAULT_WHISPERX_SEGMENT_MIN_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_MIN_WORD_COUNT,
    DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_TARGET_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_TARGET_WORD_COUNT,
)
from telegram_agent.core.whisperx.common.results import ModelTranscriptResult, ModelTranscriptSegment
from telegram_agent.core.whisperx.common.settings import settings
from telegram_agent.core.whisperx.segmentation import (
    SegmentSizing,
    TranscriptSegmenter,
    merge_transcript_segments,
)

logger = logging.getLogger(__name__)
DEFAULT_BUSY_RETRY_AFTER_SECONDS = 30


class WhisperXRuntime:
    def __init__(
        self,
        *,
        model_name: str,
        device: str,
        compute_type: str,
        batch_size: int,
        diarization_enabled: bool,
        hf_token: str | None,
        concurrency: int,
        merge_same_speaker_only: bool = DEFAULT_WHISPERX_MERGE_SAME_SPEAKER_ONLY,
        segment_target_duration_seconds: float = DEFAULT_WHISPERX_SEGMENT_TARGET_DURATION_SECONDS,
        segment_min_duration_seconds: float = DEFAULT_WHISPERX_SEGMENT_MIN_DURATION_SECONDS,
        segment_max_duration_seconds: float = DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
        segment_target_word_count: int = DEFAULT_WHISPERX_SEGMENT_TARGET_WORD_COUNT,
        segment_min_word_count: int = DEFAULT_WHISPERX_SEGMENT_MIN_WORD_COUNT,
        segment_max_word_count: int = DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
        segment_pause_seconds: float = DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("whisperx_batch_size must be greater than zero")

        if concurrency <= 0:
            raise ValueError("whisperx_concurrency must be greater than zero")

        if diarization_enabled and not hf_token:
            raise ValueError(
                "WHISPERX_HF_TOKEN is required when diarization is enabled"
            )

        self._model_name = model_name
        self._device = device
        self._compute_type = compute_type
        self._batch_size = batch_size
        self._diarization_enabled = diarization_enabled
        self._hf_token = hf_token
        self._semaphore = asyncio.Semaphore(concurrency)
        self._capacity_lock = asyncio.Lock()
        self._align_cache_lock = threading.Lock()
        self._merge_same_speaker_only = merge_same_speaker_only
        self._segment_sizing = SegmentSizing(
            target_duration_seconds=segment_target_duration_seconds,
            min_duration_seconds=segment_min_duration_seconds,
            max_duration_seconds=segment_max_duration_seconds,
            target_word_count=segment_target_word_count,
            min_word_count=segment_min_word_count,
            max_word_count=segment_max_word_count,
            pause_seconds=segment_pause_seconds,
        )
        self._segmenter = TranscriptSegmenter(self._segment_sizing)

        whisperx_module = importlib.import_module("whisperx")

        self._whisperx = whisperx_module
        self._model = whisperx_module.load_model(
            model_name,
            device,
            compute_type=compute_type,
        )
        self._align_models: dict[str, tuple[Any, Any]] = {}
        self._diarization_pipeline = None
        self._assign_word_speakers = None
        if diarization_enabled:
            diarize_module = importlib.import_module("whisperx.diarize")
            self._diarization_pipeline = diarize_module.DiarizationPipeline(
                token=hf_token,
                device=device,
            )
            self._assign_word_speakers = diarize_module.assign_word_speakers

        logger.info(
            "WhisperX runtime loaded: model=%s device=%s compute_type=%s diarization=%s concurrency=%s",
            model_name,
            device,
            compute_type,
            diarization_enabled,
            concurrency,
        )

    @classmethod
    def from_settings(cls) -> "WhisperXRuntime":
        return cls(
            model_name=settings.whisperx_model,
            device=settings.whisperx_device,
            compute_type=settings.whisperx_compute_type,
            batch_size=settings.whisperx_batch_size,
            diarization_enabled=settings.whisperx_diarization_enabled,
            hf_token=settings.whisperx_hf_token,
            concurrency=settings.whisperx_concurrency,
            merge_same_speaker_only=settings.whisperx_merge_same_speaker_only,
            segment_target_duration_seconds=(
                settings.whisperx_segment_target_duration_seconds
            ),
            segment_min_duration_seconds=settings.whisperx_segment_min_duration_seconds,
            segment_max_duration_seconds=settings.whisperx_segment_max_duration_seconds,
            segment_target_word_count=settings.whisperx_segment_target_word_count,
            segment_min_word_count=settings.whisperx_segment_min_word_count,
            segment_max_word_count=settings.whisperx_segment_max_word_count,
            segment_pause_seconds=settings.whisperx_segment_pause_seconds,
        )

    @property
    def model_name(self) -> str:
        return self._model_name

    async def transcribe(
        self,
        *,
        audio_path: Path,
        language: str | None = None,
    ) -> ModelTranscriptResult:
        await self._acquire_capacity_slot()

        try:
            return await run_in_threadpool(
                self._transcribe_sync,
                audio_path,
                language,
            )
        except WhisperXBackendBusyError:
            raise
        except Exception as exc:
            raise WhisperXBackendUnavailableError(
                "WhisperX transcription failed"
            ) from exc
        finally:
            self._semaphore.release()

    def transcribe_sync(
        self,
        *,
        audio_path: Path,
        language: str | None = None,
    ) -> ModelTranscriptResult:
        """Run one complete logical transcription in the current process."""
        return self._transcribe_sync(audio_path, language)

    async def _acquire_capacity_slot(self) -> None:
        async with self._capacity_lock:
            if self._semaphore.locked():
                raise WhisperXBackendBusyError()

            await self._semaphore.acquire()

    def _transcribe_sync(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> ModelTranscriptResult:
        audio = self._whisperx.load_audio(str(audio_path))
        result = self._model.transcribe(
            audio,
            batch_size=self._batch_size,
            language=language,
        )

        transcript_language = self._normalize_text(result.get("language")) or language
        processed_result = dict(result)

        if transcript_language:
            try:
                align_model, metadata = self._get_align_resources(transcript_language)
                processed_result = self._whisperx.align(
                    result["segments"],
                    align_model,
                    metadata,
                    audio,
                    self._device,
                    return_char_alignments=False,
                )
                processed_result["language"] = transcript_language
            except Exception:
                logger.exception(
                    "WhisperX alignment failed, falling back to raw segments: language=%s path=%s",
                    transcript_language,
                    audio_path,
                )
                processed_result = dict(result)
                processed_result["language"] = transcript_language

        if self._diarization_pipeline is not None:
            diarization_segments = self._diarization_pipeline(audio)
            if self._assign_word_speakers is None:
                raise RuntimeError("WhisperX diarization assignment is not initialized")

            processed_result = self._assign_word_speakers(
                diarization_segments,
                processed_result,
            )

        processed_result["segments"] = self._post_process_segments(
            processed_result.get("segments") or []
        )

        result = self._build_result(processed_result)
        merged_segments = merge_transcript_segments(
            result.segments,
            same_speaker_only=self._merge_same_speaker_only,
            max_duration_seconds=self._segment_sizing.max_duration_seconds,
            max_word_count=self._segment_sizing.max_word_count,
            pause_seconds=self._segment_sizing.pause_seconds,
        )
        if len(merged_segments) != len(result.segments):
            logger.info(
                "Merged Whisper segments: %s -> %s (same_speaker_only=%s)",
                len(result.segments),
                len(merged_segments),
                self._merge_same_speaker_only,
            )
        return ModelTranscriptResult(
            text=result.text,
            segments=merged_segments,
            language=result.language,
            language_probability=result.language_probability,
            duration_seconds=result.duration_seconds,
        )

    def _get_align_resources(
        self,
        language: str,
    ) -> tuple[Any, Any]:
        with self._align_cache_lock:
            cached = self._align_models.get(language)

            if cached is not None:
                return cached

            align_model, metadata = self._whisperx.load_align_model(
                language_code=language,
                device=self._device,
            )
            cached = (align_model, metadata)
            self._align_models[language] = cached
            return cached

    def _build_result(
        self,
        payload: dict[str, Any],
    ) -> ModelTranscriptResult:
        segments: list[ModelTranscriptSegment] = []

        for raw_segment in payload.get("segments") or []:
            if not isinstance(raw_segment, dict):
                continue

            start = self._get_float(raw_segment, "start")
            end = self._get_float(raw_segment, "end")
            text = self._normalize_text(raw_segment.get("text"))

            if start is None or end is None or not text:
                continue

            segments.append(
                ModelTranscriptSegment(
                    start_seconds=start,
                    end_seconds=end,
                    text=text,
                    language=self._normalize_text(raw_segment.get("language")),
                    language_probability=self._get_float(
                        raw_segment,
                        "language_probability",
                    ),
                    speaker=self._normalize_text(raw_segment.get("speaker")),
                    speaker_confidence=self._get_float(
                        raw_segment,
                        "speaker_confidence",
                        "speaker_probability",
                    ),
                    word_count=self._get_int(raw_segment, "word_count"),
                )
            )

        text = self._normalize_text(payload.get("text"))

        if not text and segments:
            text = " ".join(segment.text for segment in segments).strip()

        duration_seconds = self._get_float(payload, "duration", "duration_seconds")

        if duration_seconds is None and segments:
            duration_seconds = max(segment.end_seconds for segment in segments)

        return ModelTranscriptResult(
            text=text or "",
            segments=segments,
            language=self._normalize_text(payload.get("language")),
            language_probability=self._get_float(payload, "language_probability"),
            duration_seconds=duration_seconds,
        )

    def _post_process_segments(
        self,
        raw_segments: list[Any],
    ) -> list[dict[str, Any]]:
        return self._segmenter.post_process_segments(raw_segments)

    def _get_int(
        self,
        data: dict[str, Any],
        *keys: str,
    ) -> int | None:
        for key in keys:
            value = data.get(key)
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
        return None

    def _get_float(
        self,
        data: dict[str, Any],
        *keys: str,
    ) -> float | None:
        for key in keys:
            value = data.get(key)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return None

    def _normalize_text(
        self,
        value: object,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        return text
