from __future__ import annotations

from dataclasses import dataclass

from telegram_agent.core.common.gpu_workloads import (
    SENSEVOICE_EMOTION_BATCH_WORKLOAD,
    WHISPERX_TRANSCRIPTION_WORKLOAD,
)


@dataclass(frozen=True)
class WorkloadDefinition:
    handler_module: str
    output_kind: str = "binary"


# This registry intentionally contains import paths rather than imported handler
# objects. The API and the long-lived Celery parent therefore never import torch,
# WhisperX, FunASR, or any model-bearing module.
WORKLOAD_REGISTRY: dict[str, WorkloadDefinition] = {
    WHISPERX_TRANSCRIPTION_WORKLOAD: WorkloadDefinition(
        handler_module=(
            "telegram_agent.core.gpu_execution.workloads.whisperx_transcription"
        ),
        output_kind="json",
    ),
    SENSEVOICE_EMOTION_BATCH_WORKLOAD: WorkloadDefinition(
        handler_module=(
            "telegram_agent.core.gpu_execution.workloads.sensevoice_emotion_batch"
        ),
        output_kind="json",
    ),
}


def get_workload_definition(workload_type: str) -> WorkloadDefinition | None:
    return WORKLOAD_REGISTRY.get(workload_type)
