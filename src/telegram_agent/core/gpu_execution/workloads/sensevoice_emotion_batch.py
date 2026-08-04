from __future__ import annotations

import json
from pathlib import Path

from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
)
from telegram_agent.core.sensevoice.common.settings import settings
from telegram_agent.core.sensevoice.runtime import SenseVoiceRuntime


class SenseVoiceEmotionBatchWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        requested_model = str(parameters.get("model") or settings.sensevoice_model)
        if requested_model != settings.sensevoice_model:
            raise GpuWorkloadPermanentError(
                f"SenseVoice model {requested_model!r} is not installed in this worker"
            )
        try:
            payload = json.loads(input_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GpuWorkloadPermanentError(
                "SenseVoice batch manifest is missing or invalid"
            ) from exc
        raw_segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(raw_segments, list):
            raise GpuWorkloadPermanentError(
                "SenseVoice batch manifest must contain a segments list"
            )

        # One model instance serves every clip belonging to this logical content job.
        runtime = SenseVoiceRuntime.from_settings()
        results: list[dict[str, object]] = []
        for raw_segment in raw_segments:
            if not isinstance(raw_segment, dict):
                raise GpuWorkloadPermanentError("Invalid SenseVoice segment manifest entry")
            try:
                segment_index = int(raw_segment["segment_index"])
                clip_path = Path(str(raw_segment["path"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise GpuWorkloadPermanentError(
                    "Invalid SenseVoice segment manifest entry"
                ) from exc
            if clip_path.is_symlink() or not clip_path.is_file() or clip_path.stat().st_size <= 0:
                raise GpuWorkloadPermanentError(
                    f"SenseVoice clip for segment {segment_index} is missing or invalid"
                )
            raw_language = raw_segment.get("language")
            language = str(raw_language).strip() if raw_language is not None else None
            result = runtime.extract_emotion_sync(
                audio_path=clip_path,
                language=language or None,
            )
            results.append(
                {
                    "segment_index": segment_index,
                    "emotion": result.emotion,
                    "events": list(result.events),
                    "language": result.language,
                    "text": result.text,
                }
            )
        output_path.write_text(
            json.dumps({"segments": results}, ensure_ascii=False),
            encoding="utf-8",
        )


def create_handler() -> GpuWorkloadHandler:
    return SenseVoiceEmotionBatchWorkload()
