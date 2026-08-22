from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from telegram_agent.core.gpu_execution.workloads.madlad_engine import (
    ADAPTER_CONFIG_NAME,
    ADAPTER_WEIGHTS_NAME,
    MadladEngine,
    fix_madlad_embeddings,
    sha256_file,
)
from telegram_agent.core.gpu_execution.workloads.madlad_languages import UnknownLanguageError


class _BaseModel:
    def __init__(self) -> None:
        self.decoder = SimpleNamespace(embed_tokens=object())
        self.config = SimpleNamespace(tie_word_embeddings=True, use_cache=False)
        self.input_embeddings = None

    def set_input_embeddings(self, embeddings) -> None:
        self.input_embeddings = embeddings


class _PeftModel:
    def __init__(self, base, path: str) -> None:
        self.base = base
        self.path = path
        self.config = base.config
        self.device = "cpu"
        self.eval_called = False
        self.generate_calls: list[dict] = []

    def eval(self) -> None:
        self.eval_called = True

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return [[1] for _ in kwargs["input_ids"]]


class _Tokenizer:
    unk_token_id = 0
    pad_token_id = 1

    def __init__(self) -> None:
        self.last_texts: list[str] = []

    def convert_tokens_to_ids(self, token: str) -> int:
        return 42 if token in {"<2fa>", "<2abc>"} else 0

    def __call__(self, texts, **kwargs):
        self.last_texts = list(texts)

        class _Tensor(list):
            def to(self, device):
                return self

        return {
            "input_ids": _Tensor([[1, 2] for _ in texts]),
            "attention_mask": _Tensor([[1, 1] for _ in texts]),
        }

    def batch_decode(self, generated, skip_special_tokens=True):
        return [f"out-{index}" for index, _ in enumerate(generated)]


def _engine(adapter_dir: Path) -> MadladEngine:
    return MadladEngine(
        model_id="google/madlad400-3b-mt",
        adapter_dir=str(adapter_dir),
        device="cuda",
        max_batch_size=8,
        default_beam_size=4,
        default_max_new_tokens=256,
        max_source_length=256,
        max_input_chars=4000,
    )


def _write_adapter(path: Path) -> None:
    (path / ADAPTER_CONFIG_NAME).write_text("{}", encoding="utf-8")
    (path / ADAPTER_WEIGHTS_NAME).write_bytes(b"adapter")


def test_repairs_embeddings() -> None:
    base = _BaseModel()
    result = fix_madlad_embeddings(base)
    assert result.input_embeddings is base.decoder.embed_tokens
    assert not result.config.tie_word_embeddings


def test_translation_prefixes_target_and_preserves_empty_entries(tmp_path: Path) -> None:
    _write_adapter(tmp_path)
    engine = _engine(tmp_path)
    base = fix_madlad_embeddings(_BaseModel())
    engine._base_model = base
    engine._model = _PeftModel(base, str(tmp_path))
    engine._tokenizer = _Tokenizer()
    engine.ready = True

    result = engine.translate_batch(
        ["Hello", "  ", "world"], source_lang="en", target_lang="fa"
    )

    assert result == ["out-0", "", "out-1"]
    assert engine._tokenizer.last_texts == ["<2fa> Hello", "<2fa> world"]
    assert engine._model.generate_calls[0]["num_beams"] == 4


def test_tokenizer_rejects_unknown_target(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    base = fix_madlad_embeddings(_BaseModel())
    engine._model = _PeftModel(base, str(tmp_path))
    engine._tokenizer = _Tokenizer()
    engine.ready = True
    with pytest.raises(UnknownLanguageError):
        engine.translate_batch(["Hello"], target_lang="xyz")


def test_reload_validates_and_attaches_adapter(tmp_path: Path) -> None:
    _write_adapter(tmp_path)
    engine = _engine(tmp_path)
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    with patch(
        "telegram_agent.core.gpu_execution.workloads.madlad_engine.load_peft_adapter",
        side_effect=_PeftModel,
    ):
        sha = engine.reload_adapter()
    assert sha == sha256_file(tmp_path / ADAPTER_WEIGHTS_NAME)
    assert engine.adapter_loaded
