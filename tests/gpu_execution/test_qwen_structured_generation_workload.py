from __future__ import annotations

import json
from pathlib import Path

import pytest

from telegram_agent.core.common.gpu_workloads import QWEN_STRUCTURED_GENERATION_WORKLOAD
from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)
from telegram_agent.core.gpu_execution.workloads.qwen_engine import (
    QwenEngineError,
    extract_json_text,
    parse_json_object,
)
from telegram_agent.core.gpu_execution.workloads.qwen_structured_generation import (
    QwenStructuredGenerationWorkload,
    validate_against_schema,
)
from telegram_agent.core.llm_gateway.common.schemas import DownloadAgentVideoResponse


class _FakeEngine:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = list(outputs)
        self.loaded = False
        self.closed = False
        self.calls: list[dict[str, object]] = []

    def load(self) -> None:
        self.loaded = True

    def generate_json(self, messages, json_schema, *, max_new_tokens, temperature):
        self.calls.append(
            {
                "messages": list(messages),
                "json_schema": json_schema,
                "max_new_tokens": max_new_tokens,
                "temperature": temperature,
            }
        )
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


def _schema() -> dict[str, object]:
    return DownloadAgentVideoResponse.model_json_schema()


def _valid_output() -> dict[str, object]:
    return {
        "is_download_request": True,
        "requested_subtitle_language": "en",
        "requested_dub_language": None,
        "assistant_text": "Preparing the video.",
    }


def test_qwen_workload_uses_isolated_runtime() -> None:
    definition = get_workload_definition(QWEN_STRUCTURED_GENERATION_WORKLOAD)
    assert definition is not None
    assert definition.python_executable == "/opt/qwen/bin/python"
    assert definition.output_kind == "json"
    assert definition.handler_module.endswith("qwen_structured_generation")


def test_generates_validated_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine(
        [(_valid_output(), {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6})]
    )
    monkeypatch.setenv("QWEN_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
    monkeypatch.setattr(
        "telegram_agent.core.gpu_execution.workloads.qwen_structured_generation._build_engine",
        lambda **kwargs: engine,
    )
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "system_prompt": "system",
                "user_prompt": "user",
                "json_schema": _schema(),
                "max_validation_attempts": 3,
                "max_new_tokens": 128,
                "temperature": 0.2,
            }
        ),
        encoding="utf-8",
    )

    QwenStructuredGenerationWorkload().execute(
        input_path=input_path,
        output_path=output_path,
        parameters={"model": "Qwen/Qwen3-4B-Instruct-2507"},
    )

    assert engine.loaded
    assert engine.closed
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["output"] == _valid_output()
    assert payload["attempts"] == 1
    assert payload["model"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert payload["usage"]["total_tokens"] == 6


def test_retries_invalid_json_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine(
        [
            QwenEngineError("not json"),
            (
                _valid_output(),
                {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            ),
        ]
    )
    monkeypatch.setenv("QWEN_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
    monkeypatch.setattr(
        "telegram_agent.core.gpu_execution.workloads.qwen_structured_generation._build_engine",
        lambda **kwargs: engine,
    )
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "system_prompt": "system",
                "user_prompt": "user",
                "json_schema": _schema(),
                "max_validation_attempts": 3,
            }
        ),
        encoding="utf-8",
    )

    QwenStructuredGenerationWorkload().execute(
        input_path=input_path,
        output_path=output_path,
        parameters={"model": "Qwen/Qwen3-4B-Instruct-2507"},
    )

    assert len(engine.calls) == 2
    assert engine.calls[1]["temperature"] == pytest.approx(0.4)
    follow_up = engine.calls[1]["messages"][-1]
    assert follow_up["role"] == "user"
    assert "invalid" in follow_up["content"].lower()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["attempts"] == 2


def test_exhausted_validation_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine(
        [
            ({"is_download_request": True}, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
            ({"is_download_request": True}, {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
        ]
    )
    monkeypatch.setenv("QWEN_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
    monkeypatch.setattr(
        "telegram_agent.core.gpu_execution.workloads.qwen_structured_generation._build_engine",
        lambda **kwargs: engine,
    )
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "system_prompt": "system",
                "user_prompt": "user",
                "json_schema": _schema(),
                "max_validation_attempts": 2,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GpuWorkloadRetryableError):
        QwenStructuredGenerationWorkload().execute(
            input_path=input_path,
            output_path=output_path,
            parameters={"model": "Qwen/Qwen3-4B-Instruct-2507"},
        )
    assert engine.closed


def test_model_mismatch_is_permanent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QWEN_MODEL_ID", "Qwen/Qwen3-4B-Instruct-2507")
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "system_prompt": "system",
                "user_prompt": "user",
                "json_schema": _schema(),
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(GpuWorkloadPermanentError, match="not installed"):
        QwenStructuredGenerationWorkload().execute(
            input_path=input_path,
            output_path=tmp_path / "output.json",
            parameters={"model": "other-model"},
        )


def test_missing_schema_is_permanent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"system_prompt": "system", "user_prompt": "user"}),
        encoding="utf-8",
    )
    with pytest.raises(GpuWorkloadPermanentError, match="json_schema"):
        QwenStructuredGenerationWorkload().execute(
            input_path=input_path,
            output_path=tmp_path / "output.json",
            parameters={"model": "Qwen/Qwen3-4B-Instruct-2507"},
        )


def test_validate_against_schema_rejects_extra_fields() -> None:
    with pytest.raises(ValueError, match="Unexpected property"):
        validate_against_schema(
            {**_valid_output(), "extra": True},
            _schema(),
        )


def test_validate_against_schema_accepts_video_payload() -> None:
    validate_against_schema(_valid_output(), _schema())


def test_parse_json_object_extracts_fenced_payload() -> None:
    parsed = parse_json_object(
        '```json\n{"is_download_request": false, "assistant_text": "no"}\n```'
    )
    assert parsed["is_download_request"] is False
    assert extract_json_text("prefix {\"a\": 1} suffix") == '{"a": 1}'
