from __future__ import annotations

import asyncio
import importlib
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.concurrency import run_in_threadpool

from telegram_agent.core.common.exceptions import WhisperXBackendBusyError, WhisperXBackendUnavailableError
from telegram_agent.core.whisperx.common.results import ModelTranscriptResult, ModelTranscriptSegment
from telegram_agent.core.whisperx.common.settings import settings

logger = logging.getLogger(__name__)
DEFAULT_BUSY_RETRY_AFTER_SECONDS = 30





@dataclass(frozen=True)
class _SegmentWord:
    text: str
    speaker: str | None
    start_seconds: float | None
    end_seconds: float | None
    speaker_confidence: float | None


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

        return self._build_result(processed_result)

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
        normalized_segments: list[dict[str, Any]] = []

        for raw_segment in raw_segments:
            if not isinstance(raw_segment, dict):
                continue

            split_segments = self._split_segment_by_speaker(raw_segment)

            if split_segments is None:
                normalized_segments.append(raw_segment)
                continue

            normalized_segments.extend(split_segments)

        return normalized_segments

    def _split_segment_by_speaker(
        self,
        raw_segment: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        raw_words = raw_segment.get("words")

        if not isinstance(raw_words, list) or not raw_words:
            return None

        words = self._extract_segment_words(raw_words)

        if not words:
            return None

        if not any(word.speaker for word in words):
            return None

        grouped_words: list[list[_SegmentWord]] = []
        grouped_speakers: list[str | None] = []
        current_words: list[_SegmentWord] = []
        current_speaker: str | None = None

        for word in words:
            if (
                current_words
                and word.speaker is not None
                and current_speaker is not None
                and word.speaker != current_speaker
            ):
                grouped_words.append(current_words)
                grouped_speakers.append(current_speaker)
                current_words = []
                current_speaker = word.speaker

            if current_speaker is None and word.speaker is not None:
                current_speaker = word.speaker

            current_words.append(word)

        if current_words:
            grouped_words.append(current_words)
            grouped_speakers.append(current_speaker)

        if not grouped_words:
            return None

        normalized_segments: list[dict[str, Any]] = []

        for index, group_words in enumerate(grouped_words):
            speaker = grouped_speakers[index]

            if speaker is None:
                return None

            segment = self._build_speaker_homogeneous_segment(
                raw_segment=raw_segment,
                group_words=group_words,
                speaker=speaker,
                previous_segment=normalized_segments[-1] if normalized_segments else None,
                next_group_words=(
                    grouped_words[index + 1]
                    if index + 1 < len(grouped_words)
                    else None
                ),
            )

            if segment is None:
                return None

            normalized_segments.append(segment)

        return normalized_segments

    def _build_speaker_homogeneous_segment(
        self,
        *,
        raw_segment: dict[str, Any],
        group_words: list[_SegmentWord],
        speaker: str,
        previous_segment: dict[str, Any] | None,
        next_group_words: list[_SegmentWord] | None,
    ) -> dict[str, Any] | None:
        text = self._join_word_texts([word.text for word in group_words])

        if not text:
            return None

        raw_start = self._get_float(raw_segment, "start")
        raw_end = self._get_float(raw_segment, "end")

        start = self._first_word_start(group_words)
        end = self._last_word_end(group_words)

        if group_words[0].start_seconds is None:
            if previous_segment is not None:
                start = self._get_float(previous_segment, "end")
            elif raw_start is not None:
                start = raw_start

        if group_words[-1].end_seconds is None:
            if next_group_words is not None:
                end = self._first_word_start(next_group_words)

            if end is None and raw_end is not None:
                end = raw_end

        if end is None and raw_end is not None:
            end = raw_end

        if start is None and raw_start is not None:
            start = raw_start

        if start is None or end is None or end < start:
            return None

        segment: dict[str, Any] = {
            "start": start,
            "end": end,
            "text": text,
            "language": raw_segment.get("language"),
            "language_probability": raw_segment.get("language_probability"),
            "speaker": speaker,
        }

        speaker_confidence = self._average_speaker_confidence(group_words)

        if speaker_confidence is not None:
            segment["speaker_confidence"] = speaker_confidence

        return segment

    def _extract_segment_words(
        self,
        raw_words: list[Any],
    ) -> list[_SegmentWord]:
        words: list[_SegmentWord] = []

        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                continue

            text = self._extract_word_text(raw_word)

            if text is None:
                continue

            words.append(
                _SegmentWord(
                    text=text,
                    speaker=self._normalize_text(raw_word.get("speaker")),
                    start_seconds=self._get_float(raw_word, "start"),
                    end_seconds=self._get_float(raw_word, "end"),
                    speaker_confidence=self._get_float(
                        raw_word,
                        "speaker_confidence",
                        "speaker_probability",
                    ),
                )
            )

        return words

    def _extract_word_text(
        self,
        raw_word: dict[str, Any],
    ) -> str | None:
        for key in ("word", "text"):
            value = raw_word.get(key)

            if value is None:
                continue

            text = str(value)

            if text.strip():
                return text

        return None

    def _join_word_texts(
        self,
        raw_words: list[str],
    ) -> str:
        parts: list[str] = []

        for raw_word in raw_words:
            if not raw_word.strip():
                continue

            if not parts:
                parts.append(raw_word.strip())
                continue

            stripped_word = raw_word.strip()

            if raw_word[:1].isspace():
                parts.append(raw_word)
                continue

            if stripped_word.startswith(("'", ".", ",", "!", "?", ":", ";", "%", ")", "]", "}")):
                parts.append(stripped_word)
                continue

            if stripped_word.startswith("n't"):
                parts.append(stripped_word)
                continue

            parts.append(f" {stripped_word}")

        return "".join(parts).strip()

    def _first_word_start(
        self,
        words: list[_SegmentWord],
    ) -> float | None:
        for word in words:
            if word.start_seconds is not None:
                return word.start_seconds

        return None

    def _last_word_end(
        self,
        words: list[_SegmentWord],
    ) -> float | None:
        for word in reversed(words):
            if word.end_seconds is not None:
                return word.end_seconds

        return None

    def _average_speaker_confidence(
        self,
        words: list[_SegmentWord],
    ) -> float | None:
        values = [
            word.speaker_confidence
            for word in words
            if word.speaker_confidence is not None
        ]

        if not values:
            return None

        return sum(values) / len(values)

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
