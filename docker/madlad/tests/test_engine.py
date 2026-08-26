from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from telegram_agent.core.gpu_execution.workloads.madlad_engine import (
    ADAPTER_CONFIG_NAME,
    ADAPTER_WEIGHTS_NAME,
    MadladEngine,
    adapter_files_complete,
    fix_madlad_embeddings,
    sha256_file,
)
from telegram_agent.core.gpu_execution.workloads.madlad_languages import (
    UnknownLanguageError,
    parse_lora_languages,
)


class _BaseModel:
    def __init__(self) -> None:
        self.decoder = SimpleNamespace(embed_tokens=object())
        self.config = SimpleNamespace(tie_word_embeddings=True, use_cache=False)
        self.input_embeddings = None

    def set_input_embeddings(self, embeddings) -> None:
        self.input_embeddings = embeddings

    def eval(self) -> None:
        return None


class _PeftModel:
    def __init__(self, base, path: str, adapter_name: str = "default") -> None:
        self.base = base
        self.path = path
        self.config = base.config
        self.device = "cpu"
        self.eval_called = False
        self.generate_calls: list[dict] = []
        self.adapters = {adapter_name: path}
        self.active_adapter = adapter_name
        self.adapters_enabled = True

    def eval(self) -> None:
        self.eval_called = True

    def generate(self, **kwargs):
        self.generate_calls.append(kwargs)
        return [[1] for _ in kwargs["input_ids"]]

    def set_adapter(self, name: str) -> None:
        self.active_adapter = name
        self.adapters_enabled = True

    def enable_adapter_layers(self) -> None:
        self.adapters_enabled = True

    def disable_adapter_layers(self) -> None:
        self.adapters_enabled = False

    def load_adapter(self, path: str, adapter_name: str) -> None:
        self.adapters[adapter_name] = path


class _Tokenizer:
    unk_token_id = 0
    pad_token_id = 1

    def __init__(self) -> None:
        self.last_texts: list[str] = []

    def convert_tokens_to_ids(self, token: str) -> int:
        if token == "<2xyz>":
            return 0
        if token.startswith("<2") and token.endswith(">"):
            return 42
        return 0

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


def _engine(adapter_dir: Path, lora_languages: str | tuple[str, ...] = "fa") -> MadladEngine:
    return MadladEngine(
        model_id="google/madlad400-3b-mt",
        adapter_dir=str(adapter_dir),
        lora_languages=lora_languages,
        device="cuda",
        max_batch_size=8,
        default_beam_size=4,
        default_max_new_tokens=256,
        max_source_length=256,
        max_input_chars=4000,
    )


def _write_adapter(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / ADAPTER_CONFIG_NAME).write_text("{}", encoding="utf-8")
    (path / ADAPTER_WEIGHTS_NAME).write_bytes(b"adapter")


def _ready_engine(engine: MadladEngine, model) -> None:
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    engine._model = model
    engine._tokenizer = _Tokenizer()
    engine.ready = True


def test_repairs_embeddings() -> None:
    base = _BaseModel()
    result = fix_madlad_embeddings(base)
    assert result.input_embeddings is base.decoder.embed_tokens
    assert not result.config.tie_word_embeddings


def test_parse_lora_languages() -> None:
    assert parse_lora_languages(None) == ()
    assert parse_lora_languages("") == ()
    assert parse_lora_languages("fa") == ("fa",)
    assert parse_lora_languages(" fa, es ") == ("fa", "es")
    assert parse_lora_languages("Persian") == ("fa",)
    assert parse_lora_languages("fa, fa, Persian") == ("fa",)
    assert parse_lora_languages("fa, not a language") == ("fa",)


def test_translation_prefixes_target_and_preserves_empty_entries(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _ready_engine(engine, _PeftModel(fix_madlad_embeddings(_BaseModel()), str(tmp_path)))

    result = engine.translate_batch(
        ["Hello", "  ", "world"], source_lang="en", target_lang="fa"
    )

    assert result == ["out-0", "", "out-1"]
    assert engine._tokenizer.last_texts == ["<2fa> Hello", "<2fa> world"]
    assert engine._model.generate_calls[0]["num_beams"] == 4


def test_tokenizer_rejects_unknown_target(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    _ready_engine(engine, _PeftModel(fix_madlad_embeddings(_BaseModel()), str(tmp_path)))
    with pytest.raises(UnknownLanguageError):
        engine.translate_batch(["Hello"], target_lang="xyz")


def test_missing_adapter_uses_base_model(tmp_path: Path) -> None:
    engine = _engine(tmp_path, lora_languages="fa")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    engine._attach_available_adapters()
    assert engine._model is engine._base_model
    assert not engine.adapter_loaded
    assert engine._loaded_adapters == {}
    assert engine.adapter_sha256 is None


def test_incomplete_adapter_is_skipped(tmp_path: Path) -> None:
    fa_dir = tmp_path / "fa"
    fa_dir.mkdir()
    (fa_dir / ADAPTER_CONFIG_NAME).write_text("{}", encoding="utf-8")
    engine = _engine(tmp_path, lora_languages="fa")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    engine._attach_available_adapters()
    assert engine._model is engine._base_model
    assert not engine.adapter_loaded
    assert not adapter_files_complete(fa_dir)


def test_attaches_named_adapter_when_present(tmp_path: Path) -> None:
    fa_dir = tmp_path / "fa"
    _write_adapter(fa_dir)
    engine = _engine(tmp_path, lora_languages="fa")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    with patch(
        "telegram_agent.core.gpu_execution.workloads.madlad_engine.load_peft_adapter",
        side_effect=_PeftModel,
    ):
        engine._attach_available_adapters()
    assert engine.adapter_loaded
    assert engine._loaded_adapters["fa"] == fa_dir
    assert engine._active_adapter == "fa"
    assert engine.adapter_sha256 == sha256_file(fa_dir / ADAPTER_WEIGHTS_NAME)
    assert engine._model.active_adapter == "fa"


def test_unlisted_language_adapter_is_not_loaded(tmp_path: Path) -> None:
    _write_adapter(tmp_path / "fa")
    engine = _engine(tmp_path, lora_languages="")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    with patch(
        "telegram_agent.core.gpu_execution.workloads.madlad_engine.load_peft_adapter",
        side_effect=_PeftModel,
    ) as load_adapter:
        engine._attach_available_adapters()
    load_adapter.assert_not_called()
    assert engine._model is engine._base_model
    assert not engine.adapter_loaded


def test_translate_activates_matching_adapter_only(tmp_path: Path) -> None:
    fa_dir = tmp_path / "fa"
    _write_adapter(fa_dir)
    engine = _engine(tmp_path, lora_languages="fa")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    with patch(
        "telegram_agent.core.gpu_execution.workloads.madlad_engine.load_peft_adapter",
        side_effect=_PeftModel,
    ):
        engine._attach_available_adapters()
    engine._tokenizer = _Tokenizer()
    engine.ready = True

    engine.translate_batch(["Hello"], target_lang="es")
    assert engine._model.active_adapter == "fa"
    assert engine._model.adapters_enabled is False
    assert engine.adapter_sha256 is None
    assert engine._active_adapter is None

    engine.translate_batch(["Hello"], target_lang="fa")
    assert engine._model.active_adapter == "fa"
    assert engine._model.adapters_enabled is True
    assert engine.adapter_sha256 == sha256_file(fa_dir / ADAPTER_WEIGHTS_NAME)


def test_reload_attaches_present_adapters_and_skips_missing(tmp_path: Path) -> None:
    fa_dir = tmp_path / "fa"
    _write_adapter(fa_dir)
    engine = _engine(tmp_path, lora_languages="fa,es")
    engine._base_model = fix_madlad_embeddings(_BaseModel())
    with patch(
        "telegram_agent.core.gpu_execution.workloads.madlad_engine.load_peft_adapter",
        side_effect=_PeftModel,
    ):
        sha = engine.reload_adapter()
    assert sha == sha256_file(fa_dir / ADAPTER_WEIGHTS_NAME)
    assert engine.adapter_loaded
    assert list(engine._loaded_adapters) == ["fa"]


def test_preferred_tokenizer_source_uses_adapter_when_present(tmp_path: Path) -> None:
    fa_dir = tmp_path / "fa"
    _write_adapter(fa_dir)
    (fa_dir / "tokenizer.json").write_text("{}", encoding="utf-8")
    engine = _engine(tmp_path, lora_languages="fa")
    assert engine._preferred_tokenizer_source() == str(fa_dir)


def test_preferred_tokenizer_source_falls_back_to_model_id(tmp_path: Path) -> None:
    engine = _engine(tmp_path, lora_languages="fa")
    assert engine._preferred_tokenizer_source() == "google/madlad400-3b-mt"
