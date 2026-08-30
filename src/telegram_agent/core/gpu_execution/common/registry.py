from __future__ import annotations

from dataclasses import dataclass

from telegram_agent.core.common.gpu_workloads import (
    COSYVOICE_DUBBING_BATCH_WORKLOAD,
    MADLAD_TRANSLATION_WORKLOAD,
    QWEN_STRUCTURED_GENERATION_WORKLOAD,
    SAM_AUDIO_RESIDUAL_WORKLOAD,
    WHISPERX_TRANSCRIPTION_WORKLOAD,
)


@dataclass(frozen=True)
class WorkloadDefinition:
    handler_module: str
    output_kind: str = "binary"
    python_executable: str | None = None


# This registry intentionally contains import paths rather than imported handler
# objects. The API and the long-lived Celery parent therefore never import torch,
# WhisperX, or any model-bearing module.
WORKLOAD_REGISTRY: dict[str, WorkloadDefinition] = {
    WHISPERX_TRANSCRIPTION_WORKLOAD: WorkloadDefinition(
        handler_module=(
            "telegram_agent.core.gpu_execution.workloads.whisperx_transcription"
        ),
        output_kind="json",
    ),
    COSYVOICE_DUBBING_BATCH_WORKLOAD: WorkloadDefinition(
        handler_module="telegram_agent.core.gpu_execution.workloads.cosyvoice_dubbing_batch",
        output_kind="json",
        python_executable="/opt/cosyvoice/bin/python",
    ),
    SAM_AUDIO_RESIDUAL_WORKLOAD: WorkloadDefinition(
        handler_module="telegram_agent.core.gpu_execution.workloads.sam_audio_residual",
        output_kind="json",
        python_executable="/opt/sam-audio/bin/python",
    ),
    MADLAD_TRANSLATION_WORKLOAD: WorkloadDefinition(
        handler_module="telegram_agent.core.gpu_execution.workloads.madlad_translation",
        output_kind="json",
        python_executable="/opt/madlad/bin/python",
    ),
    QWEN_STRUCTURED_GENERATION_WORKLOAD: WorkloadDefinition(
        handler_module=(
            "telegram_agent.core.gpu_execution.workloads.qwen_structured_generation"
        ),
        output_kind="json",
        python_executable="/opt/qwen/bin/python",
    ),
}


def get_workload_definition(workload_type: str) -> WorkloadDefinition | None:
    return WORKLOAD_REGISTRY.get(workload_type)
