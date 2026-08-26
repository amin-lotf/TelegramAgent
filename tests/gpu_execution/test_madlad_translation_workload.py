from __future__ import annotations

import json
from pathlib import Path

import pytest

from telegram_agent.core.common.gpu_workloads import MADLAD_TRANSLATION_WORKLOAD
from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.workloads.madlad_languages import UnknownLanguageError
from telegram_agent.core.gpu_execution.workloads.madlad_translation import (
    MadladTranslationWorkload,
    _build_engine,
)
from telegram_agent.core.gpu_execution.workloads.protocol import GpuWorkloadPermanentError


class _FakeEngine:
    def __init__(self) -> None:
        self.max_batch_size = 2
        self.adapter_sha256 = "adapter-sha"
        self.loaded = False
        self.batches: list[list[str]] = []

    def load(self) -> None:
        self.loaded = True

    def resolve_lang(self, code: str) -> str:
        if code == "bad":
            raise UnknownLanguageError("bad language")
        return "fa"

    def translate_batch(self, texts: list[str], **kwargs) -> list[str]:
        del kwargs
        self.batches.append(list(texts))
        return [f"T:{text}" for text in texts]


def test_madlad_workload_uses_isolated_runtime() -> None:
    definition = get_workload_definition(MADLAD_TRANSLATION_WORKLOAD)
    assert definition is not None
    assert definition.python_executable == "/opt/madlad/bin/python"
    assert (
        definition.handler_module
        == "telegram_agent.core.gpu_execution.workloads.madlad_translation"
    )


def test_translates_json_batch_in_engine_sized_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(
        "telegram_agent.core.gpu_execution.workloads.madlad_translation._build_engine",
        lambda **kwargs: engine,
    )
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(
        json.dumps(
            {
                "texts": ["a", "b", "c"],
                "source_lang": "en",
                "target_lang": "fa",
            }
        ),
        encoding="utf-8",
    )

    MadladTranslationWorkload().execute(
        input_path=input_path,
        output_path=output_path,
        parameters={"model": "google/madlad400-3b-mt", "max_batch_size": 2},
    )

    assert engine.loaded
    assert engine.batches == [["a", "b"], ["c"]]
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["translations"] == ["T:a", "T:b", "T:c"]
    assert payload["count"] == 3
    assert payload["target_lang"] == "fa"
    assert payload["target_token"] == "<2fa>"
    assert payload["adapter_sha256"] == "adapter-sha"


def test_unknown_language_is_permanent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _FakeEngine()
    monkeypatch.setattr(
        "telegram_agent.core.gpu_execution.workloads.madlad_translation._build_engine",
        lambda **kwargs: engine,
    )
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"texts": ["a"], "target_lang": "bad"}),
        encoding="utf-8",
    )
    with pytest.raises(GpuWorkloadPermanentError, match="bad language"):
        MadladTranslationWorkload().execute(
            input_path=input_path,
            output_path=tmp_path / "output.json",
            parameters={"model": "google/madlad400-3b-mt"},
        )


def test_build_engine_parses_lora_languages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MADLAD_ADAPTER_DIR", str(tmp_path))
    monkeypatch.setenv("MADLAD_LOAD_LORA_FOR", "Persian, es")
    engine = _build_engine(
        model_id="google/madlad400-3b-mt",
        max_batch_size=8,
        beam_size=4,
        max_new_tokens=256,
    )
    assert engine.lora_languages == ("fa", "es")
    assert engine.adapter_dir == str(tmp_path)


def test_build_engine_empty_lora_list_loads_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MADLAD_ADAPTER_DIR", str(tmp_path))
    monkeypatch.setenv("MADLAD_LOAD_LORA_FOR", "")
    engine = _build_engine(
        model_id="google/madlad400-3b-mt",
        max_batch_size=8,
        beam_size=4,
        max_new_tokens=256,
    )
    assert engine.lora_languages == ()


def test_empty_texts_are_permanent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps({"texts": [], "target_lang": "fa"}), encoding="utf-8")
    with pytest.raises(GpuWorkloadPermanentError, match="non-empty"):
        MadladTranslationWorkload().execute(
            input_path=input_path,
            output_path=tmp_path / "output.json",
            parameters={},
        )
