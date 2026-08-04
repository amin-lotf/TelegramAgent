from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_agent.core.common.exceptions import WhisperXResponseError
from telegram_agent.core.common.gpu_workloads import WHISPERX_TRANSCRIPTION_WORKLOAD
from telegram_agent.core.common.utils import seconds_to_ms
from telegram_agent.core.content_processing.clients.gpu_execution_client import GpuExecutionClient
from telegram_agent.core.content_processing.common.results import (
    TranscriptionResult,
    TranscriptionSegmentResult,
)
from telegram_agent.core.content_processing.common.settings import Settings


class _TranscriptSegmentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    start: float
    end: float
    text: str
    language: str | None = None
    language_probability: float | None = None
    speaker: str | None = None
    speaker_confidence: float | None = None


class _TranscriptPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    text: str
    segments: list[_TranscriptSegmentPayload]
    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None


class WhisperXClient:
    """Whisper-specific adapter over the generic durable GPU execution API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gpu_client = GpuExecutionClient(settings)

    def transcribe(
        self,
        *,
        path: Path,
        mime_type: str | None,
        request_id: str,
        heartbeat: Callable[[], None] | None = None,
    ) -> TranscriptionResult:
        del mime_type
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise WhisperXResponseError("Downloaded media file is missing or invalid")
        output_path = (
            Path(self._settings.media_storage_root)
            / request_id
            / "gpu_results"
            / "whisperx_transcription.json"
        )
        result_path = self._gpu_client.execute_and_wait(
            workload_type=WHISPERX_TRANSCRIPTION_WORKLOAD,
            idempotency_key=f"{WHISPERX_TRANSCRIPTION_WORKLOAD}:{request_id}",
            input_path=path,
            output_path=output_path,
            parameters={"model": self._settings.whisperx_model},
            timeout_seconds=max(
                1,
                min(
                    int(self._settings.whisperx_request_timeout_seconds),
                    self._settings.gpu_execution_job_max_timeout_seconds,
                ),
            ),
            max_attempts=self._settings.gpu_execution_job_max_attempts,
            heartbeat=heartbeat,
        )
        try:
            response_data = _TranscriptPayload.model_validate(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise WhisperXResponseError(
                "WhisperX GPU workload returned an invalid transcription result"
            ) from exc
        segments: list[TranscriptionSegmentResult] = []
        for segment in response_data.segments:
            start_ms = seconds_to_ms(segment.start)
            end_ms = seconds_to_ms(segment.end)
            if start_ms is None or end_ms is None or end_ms < start_ms:
                raise WhisperXResponseError(
                    "WhisperX GPU workload returned an invalid transcript segment"
                )
            segments.append(
                TranscriptionSegmentResult(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=segment.text,
                    language=segment.language,
                    language_probability=segment.language_probability,
                    speaker=segment.speaker,
                    speaker_confidence=segment.speaker_confidence,
                )
            )
        return TranscriptionResult(
            text=response_data.text,
            language=response_data.language,
            language_probability=response_data.language_probability,
            duration_ms=seconds_to_ms(response_data.duration),
            segments=tuple(segments),
        )
