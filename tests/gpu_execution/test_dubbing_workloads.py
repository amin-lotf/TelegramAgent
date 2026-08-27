from __future__ import annotations

import json
import os
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from telegram_agent.core.common.gpu_workloads import (
    COSYVOICE_DUBBING_BATCH_WORKLOAD,
    SAM_AUDIO_RESIDUAL_WORKLOAD,
)
from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.workloads import cosyvoice_dubbing_batch as cosyvoice_module
from telegram_agent.core.gpu_execution.workloads.cosyvoice_dubbing_batch import (
    CosyVoiceDubbingBatchWorkload,
    _max_in_flight_segments,
    _wrap_frontend_text_normalize,
)
from telegram_agent.core.gpu_execution.workloads.protocol import GpuWorkloadPermanentError
from telegram_agent.core.gpu_execution.workloads.sam_audio_residual import (
    _chunk_windows,
    _crossfade,
    _prepare_imagebind_checkpoint_dir,
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


def test_prepare_imagebind_checkpoint_dir_chdirs_to_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint_dir = tmp_path / "cache" / ".checkpoints"
    monkeypatch.setenv("SAM_AUDIO_CHECKPOINTS_DIR", str(checkpoint_dir))
    original = Path.cwd()
    try:
        prepared = _prepare_imagebind_checkpoint_dir()
        assert prepared == checkpoint_dir.resolve()
        assert checkpoint_dir.is_dir()
        assert Path.cwd() == checkpoint_dir.parent.resolve()
    finally:
        os.chdir(original)


def test_wrap_frontend_text_normalize_unescapes_tn_entity_leaks() -> None:
    class Frontend:
        def text_normalize(self, text: str) -> str:
            return text

    class Model:
        def __init__(self) -> None:
            self.frontend = Frontend()

    model = Model()
    _wrap_frontend_text_normalize(model)
    assert model.frontend.text_normalize("It &apos;s recycled.") == "It's recycled."
    assert model.frontend.text_normalize("do n't") == "don't"


def test_max_in_flight_segments_defaults_and_rejects_out_of_range() -> None:
    assert _max_in_flight_segments({}) == 2
    assert _max_in_flight_segments({"max_in_flight_segments": 2}) == 2
    assert _max_in_flight_segments({"max_in_flight_segments": 8}) == 8
    with pytest.raises(GpuWorkloadPermanentError, match="between"):
        _max_in_flight_segments({"max_in_flight_segments": 0})
    with pytest.raises(GpuWorkloadPermanentError, match="between"):
        _max_in_flight_segments({"max_in_flight_segments": 9})
    with pytest.raises(GpuWorkloadPermanentError, match="Invalid"):
        _max_in_flight_segments({"max_in_flight_segments": "abc"})


def test_in_flight_segments_overlap_and_order_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GPU_SHARED_STORAGE_ROOT", str(tmp_path))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    segments = _segment_payloads(tmp_path, count=4)

    workload = CosyVoiceDubbingBatchWorkload()
    in_flight = 0
    max_in_flight = 0
    guard = threading.Lock()

    def fake_synthesize(self, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal in_flight, max_in_flight
        with guard:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        try:
            time.sleep(0.05)
            _write_wav(kwargs["output_path"])
            return {
                "source": "cosyvoice",
                "synthesis_speed": 1.0,
                "rubberband_tempo": None,
                "duration_seconds": 0.1,
                "target_duration_seconds": kwargs["target_seconds"],
            }
        finally:
            with guard:
                in_flight -= 1

    monkeypatch.setattr(
        CosyVoiceDubbingBatchWorkload, "_synthesize_segment", fake_synthesize
    )

    results = workload._synthesize_all_segments(
        model=object(),
        segments=segments,
        output_dir=output_dir,
        manifest_path=output_dir / "tts_manifest.json",
        installed_model="test-model",
        mode="cross_lingual",
        parameters={},
        max_in_flight_segments=2,
    )

    assert max_in_flight >= 2
    assert [item["index"] for item in results] == [0, 1, 2, 3]
    persisted = json.loads((output_dir / "tts_manifest.json").read_text(encoding="utf-8"))
    assert [item["index"] for item in persisted["segments"]] == [0, 1, 2, 3]
    for index in range(4):
        assert (output_dir / f"segment_{index:05d}.wav").is_file()


def test_in_flight_failure_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GPU_SHARED_STORAGE_ROOT", str(tmp_path))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    segments = _segment_payloads(tmp_path, count=4)
    workload = CosyVoiceDubbingBatchWorkload()

    def fake_synthesize(self, **kwargs):  # type: ignore[no-untyped-def]
        if kwargs["target_text"] == "dst 1":
            raise GpuWorkloadPermanentError("failed dst 1")
        _write_wav(kwargs["output_path"])
        return {
            "source": "cosyvoice",
            "synthesis_speed": 1.0,
            "rubberband_tempo": None,
            "duration_seconds": 0.1,
            "target_duration_seconds": kwargs["target_seconds"],
        }

    monkeypatch.setattr(
        CosyVoiceDubbingBatchWorkload, "_synthesize_segment", fake_synthesize
    )

    with pytest.raises(GpuWorkloadPermanentError, match="failed dst 1"):
        workload._synthesize_all_segments(
            model=object(),
            segments=segments,
            output_dir=output_dir,
            manifest_path=output_dir / "tts_manifest.json",
            installed_model="test-model",
            mode="cross_lingual",
            parameters={},
            max_in_flight_segments=2,
        )


def test_in_flight_resume_reuses_existing_clips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GPU_SHARED_STORAGE_ROOT", str(tmp_path))
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    segments = _segment_payloads(tmp_path, count=3)
    workload = CosyVoiceDubbingBatchWorkload()
    calls = {"count": 0}

    def fake_synthesize(self, **kwargs):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        _write_wav(kwargs["output_path"])
        return {
            "source": "cosyvoice",
            "synthesis_speed": 1.0,
            "rubberband_tempo": None,
            "duration_seconds": 0.1,
            "target_duration_seconds": kwargs["target_seconds"],
        }

    monkeypatch.setattr(
        CosyVoiceDubbingBatchWorkload, "_synthesize_segment", fake_synthesize
    )
    kwargs = {
        "model": object(),
        "segments": segments,
        "output_dir": output_dir,
        "manifest_path": output_dir / "tts_manifest.json",
        "installed_model": "test-model",
        "mode": "cross_lingual",
        "parameters": {},
        "max_in_flight_segments": 2,
    }
    first = workload._synthesize_all_segments(**kwargs)
    assert calls["count"] == 3
    resumed = workload._synthesize_all_segments(**kwargs)
    assert calls["count"] == 3
    assert [item["index"] for item in resumed] == [item["index"] for item in first]


def test_inference_lock_serializes_gpu_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    workload = CosyVoiceDubbingBatchWorkload()
    in_flight = 0
    max_in_flight = 0
    guard = threading.Lock()

    def fake_collect(chunks, *, sample_rate):  # type: ignore[no-untyped-def]
        nonlocal in_flight, max_in_flight
        with guard:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.04)
        with guard:
            in_flight -= 1
        return b"\x00\x00" * 4800, sample_rate

    monkeypatch.setattr(cosyvoice_module, "_invoke_model", lambda **kwargs: iter(()))
    monkeypatch.setattr(cosyvoice_module, "_collect_model_audio", fake_collect)

    def run() -> None:
        workload._infer_locked(
            model=object(),
            mode="cross_lingual",
            target_text="t",
            prompt_text="p",
            prompt_path=Path("/unused"),
            speed=1.0,
        )

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert max_in_flight == 1


def _segment_payloads(root: Path, *, count: int) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []
    for index in range(count):
        prompt = root / f"prompt_{index}.wav"
        _write_wav(prompt)
        segments.append(
            {
                "index": index,
                "start_ms": index * 1000,
                "end_ms": (index + 1) * 1000,
                "prompt_path": str(prompt),
                "source_text": f"src {index}",
                "target_text": f"dst {index}",
            }
        )
    return segments


def _write_wav(path: Path, *, frames: int = 2400, sample_rate: int = 24_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * frames)
