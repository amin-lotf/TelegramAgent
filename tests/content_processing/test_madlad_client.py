from __future__ import annotations

import json
from pathlib import Path

import pytest

from telegram_agent.core.common.exceptions import (
    GpuExecutionResponseError,
    GpuExecutionServiceError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.common.gpu_workloads import MADLAD_TRANSLATION_WORKLOAD
from telegram_agent.core.content_processing.clients.madlad import MadladClient
from telegram_agent.core.content_processing.common.settings import settings


class _FakeGpuClient:
    def __init__(self, *, result: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    def execute_and_wait(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        assert self.result is not None
        output_path.write_text(json.dumps(self.result), encoding="utf-8")
        return output_path


def _client(tmp_path: Path, gpu: _FakeGpuClient, monkeypatch: pytest.MonkeyPatch) -> MadladClient:
    monkeypatch.setattr(settings, "media_storage_root", str(tmp_path))
    return MadladClient(settings, gpu_client=gpu)  # type: ignore[arg-type]


def test_writes_input_and_validates_gpu_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gpu = _FakeGpuClient(
        result={
            "translations": ["سلام", "دنیا"],
            "source_lang": "en",
            "target_lang": "fa",
            "target_token": "<2fa>",
            "model": "google/madlad400-3b-mt",
            "count": 2,
            "adapter_sha256": "abc",
        }
    )
    generation = _client(tmp_path, gpu, monkeypatch).translate(
        ["Hello", "world"],
        source_lang="English",
        target_lang="Persian",
        request_id="job-1",
    )
    assert generation.translations == ["سلام", "دنیا"]
    assert len(gpu.calls) == 1
    call = gpu.calls[0]
    assert call["workload_type"] == MADLAD_TRANSLATION_WORKLOAD
    assert call["idempotency_key"] == f"{MADLAD_TRANSLATION_WORKLOAD}:job-1"
    assert call["parameters"]["model"] == settings.madlad_model
    input_path = Path(call["input_path"])
    assert json.loads(input_path.read_text(encoding="utf-8")) == {
        "texts": ["Hello", "world"],
        "source_lang": "en",
        "target_lang": "fa",
    }


def test_gpu_service_errors_are_retryable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gpu = _FakeGpuClient(error=GpuExecutionServiceError("busy"))
    with pytest.raises(RetryableContentProcessingError):
        _client(tmp_path, gpu, monkeypatch).translate(
            ["Hello"], source_lang="en", target_lang="fa", request_id="job-1"
        )


def test_gpu_response_errors_are_permanent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gpu = _FakeGpuClient(error=GpuExecutionResponseError("bad language"))
    with pytest.raises(PermanentContentProcessingError):
        _client(tmp_path, gpu, monkeypatch).translate(
            ["Hello"], source_lang="en", target_lang="fa", request_id="job-1"
        )


def test_rejects_mismatched_count_as_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gpu = _FakeGpuClient(
        result={
            "translations": ["فقط یکی"],
            "target_lang": "fa",
            "target_token": "<2fa>",
            "model": "model",
            "count": 1,
        }
    )
    with pytest.raises(RetryableContentProcessingError):
        _client(tmp_path, gpu, monkeypatch).translate(
            ["a", "b"], source_lang="en", target_lang="fa", request_id="job-1"
        )
