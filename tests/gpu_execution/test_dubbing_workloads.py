from __future__ import annotations

import numpy as np

from telegram_agent.core.common.gpu_workloads import (
    COSYVOICE_DUBBING_BATCH_WORKLOAD,
    SAM_AUDIO_RESIDUAL_WORKLOAD,
)
from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.workloads.sam_audio_residual import (
    _chunk_windows,
    _crossfade,
)


def test_dubbing_workloads_use_isolated_model_runtimes() -> None:
    cosy = get_workload_definition(COSYVOICE_DUBBING_BATCH_WORKLOAD)
    sam = get_workload_definition(SAM_AUDIO_RESIDUAL_WORKLOAD)

    assert cosy is not None and cosy.python_executable == "/opt/cosyvoice/bin/python"
    assert sam is not None and sam.python_executable == "/opt/sam-audio/bin/python"


def test_sam_chunking_and_crossfade_preserve_expected_duration() -> None:
    windows = _chunk_windows(
        total_seconds=21.0,
        chunk_seconds=10.0,
        overlap_seconds=2.5,
    )
    assert windows == [(0.0, 10.0), (7.5, 17.5), (15.0, 21.0)]

    chunks = [
        np.ones(10, dtype=np.float32),
        np.zeros(10, dtype=np.float32),
    ]
    output = _crossfade(chunks, overlap_samples=3)
    assert output.shape == (17,)
    assert np.all(output[:7] == 1.0)
    assert np.all(output[-7:] == 0.0)
