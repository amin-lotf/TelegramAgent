from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telegram_agent.core.common.exceptions import SenseVoiceResponseError
from telegram_agent.core.common.gpu_workloads import SENSEVOICE_EMOTION_BATCH_WORKLOAD
from telegram_agent.core.content_processing.clients.gpu_execution_client import GpuExecutionClient
from telegram_agent.core.content_processing.common.results import (
    EmotionExtractionBatchResult,
    SegmentEmotionUpdate,
)
from telegram_agent.core.content_processing.common.settings import Settings


class _EmotionItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    segment_index: int
    emotion: str | None = None
    events: list[str] = Field(default_factory=list)


class _EmotionBatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    segments: list[_EmotionItem]


class SenseVoiceClient:
    """SenseVoice batch adapter over the generic durable GPU execution API."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._gpu_client = GpuExecutionClient(settings)

    def extract_emotions(
        self,
        *,
        manifest_path: Path,
        request_id: str,
        timeout_seconds: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> EmotionExtractionBatchResult:
        output_path = (
            Path(self._settings.media_storage_root)
            / request_id
            / "gpu_results"
            / "sensevoice_emotions.json"
        )
        result_path = self._gpu_client.execute_and_wait(
            workload_type=SENSEVOICE_EMOTION_BATCH_WORKLOAD,
            idempotency_key=f"{SENSEVOICE_EMOTION_BATCH_WORKLOAD}:{request_id}",
            input_path=manifest_path,
            output_path=output_path,
            parameters={"model": self._settings.sensevoice_model},
            timeout_seconds=timeout_seconds,
            max_attempts=self._settings.gpu_execution_job_max_attempts,
            heartbeat=heartbeat,
        )
        try:
            payload = _EmotionBatch.model_validate(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise SenseVoiceResponseError(
                "SenseVoice GPU workload returned an invalid batch result"
            ) from exc
        seen: set[int] = set()
        updates: list[SegmentEmotionUpdate] = []
        for item in payload.segments:
            if item.segment_index in seen:
                raise SenseVoiceResponseError(
                    "SenseVoice GPU workload returned duplicate segment results"
                )
            seen.add(item.segment_index)
            updates.append(
                SegmentEmotionUpdate(
                    segment_index=item.segment_index,
                    emotion=item.emotion,
                    audio_events=tuple(item.events) or None,
                )
            )
        return EmotionExtractionBatchResult(segments=tuple(updates))
