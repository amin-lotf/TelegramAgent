from __future__ import annotations

import json
from pathlib import Path

from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
)
from telegram_agent.core.whisperx.common.settings import settings
from telegram_agent.core.whisperx.runtime import WhisperXRuntime


class WhisperXTranscriptionWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        if input_path.is_symlink() or not input_path.is_file() or input_path.stat().st_size <= 0:
            raise GpuWorkloadPermanentError("WhisperX input media is missing or invalid")
        requested_model = str(parameters.get("model") or settings.whisperx_model)
        if requested_model != settings.whisperx_model:
            raise GpuWorkloadPermanentError(
                f"WhisperX model {requested_model!r} is not installed in this worker"
            )
        raw_language = parameters.get("language")
        language = str(raw_language).strip() if raw_language is not None else None
        if language == "":
            language = None

        runtime = WhisperXRuntime.from_settings()
        result = runtime.transcribe_sync(audio_path=input_path, language=language)
        payload = {
            "text": result.text,
            "segments": [
                {
                    "start": segment.start_seconds,
                    "end": segment.end_seconds,
                    "text": segment.text,
                    "language": segment.language,
                    "language_probability": segment.language_probability,
                    "speaker": segment.speaker,
                    "speaker_confidence": segment.speaker_confidence,
                    "word_count": segment.word_count,
                }
                for segment in result.segments
            ],
            "language": result.language,
            "language_probability": result.language_probability,
            "duration": result.duration_seconds,
            "model": runtime.model_name,
        }
        output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def create_handler() -> GpuWorkloadHandler:
    return WhisperXTranscriptionWorkload()
