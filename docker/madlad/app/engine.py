"""Re-export the GPU-worker MADLAD engine for the optional HTTP service."""

from telegram_agent.core.gpu_execution.workloads.madlad_engine import (
    ADAPTER_CONFIG_NAME,
    ADAPTER_META_NAME,
    ADAPTER_WEIGHTS_NAME,
    MadladEngine,
    adapter_files_complete,
    configure_madlad_hf_home,
    fix_madlad_embeddings,
    load_peft_adapter,
    read_adapter_meta,
    sha256_file,
)

__all__ = [
    "ADAPTER_CONFIG_NAME",
    "ADAPTER_META_NAME",
    "ADAPTER_WEIGHTS_NAME",
    "MadladEngine",
    "adapter_files_complete",
    "configure_madlad_hf_home",
    "fix_madlad_embeddings",
    "load_peft_adapter",
    "read_adapter_meta",
    "sha256_file",
]
