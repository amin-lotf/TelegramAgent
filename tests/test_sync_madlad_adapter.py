from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_madlad_adapter.py"
_SPEC = importlib.util.spec_from_file_location("sync_madlad_adapter", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_copies_only_inference_files_and_writes_metadata(tmp_path: Path) -> None:
    source = tmp_path / "training-output"
    dest = tmp_path / "adapter"
    source.mkdir()
    (source / "adapter_config.json").write_text("{}", encoding="utf-8")
    (source / "adapter_model.safetensors").write_bytes(b"weights")
    (source / "tokenizer.json").write_text("{}", encoding="utf-8")
    (source / "optimizer.pt").write_bytes(b"do-not-copy")

    result = _MODULE.sync_adapter(source=source, dest=dest)

    assert result == dest.resolve()
    assert (dest / "adapter_config.json").is_file()
    assert (dest / "adapter_model.safetensors").is_file()
    assert (dest / "tokenizer.json").is_file()
    assert not (dest / "optimizer.pt").exists()
    metadata = json.loads((dest / "adapter_meta.json").read_text(encoding="utf-8"))
    assert metadata["source"] == str(source.resolve())
    assert len(metadata["sha256"]) == 64


def test_missing_required_weight_file_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "training-output"
    source.mkdir()
    (source / "adapter_config.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        _MODULE.sync_adapter(source=source, dest=tmp_path / "adapter")


def test_reads_configured_source_from_env_file(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "custom-source"
    dest = tmp_path / "adapter"
    source.mkdir()
    (source / "adapter_config.json").write_text("{}", encoding="utf-8")
    (source / "adapter_model.safetensors").write_bytes(b"weights")
    env_file = tmp_path / ".env.madlad.docker"
    env_file.write_text(
        f"MADLAD_WEIGHTS_SOURCE_PATH={source}\n", encoding="utf-8"
    )
    monkeypatch.delenv("MADLAD_WEIGHTS_SOURCE_PATH", raising=False)

    exit_code = _MODULE.main(
        ["--env-file", str(env_file), "--dest", str(dest)]
    )

    assert exit_code == 0
    assert (dest / "adapter_model.safetensors").is_file()


def test_default_dest_uses_language_directory(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "training-output"
    source.mkdir()
    (source / "adapter_config.json").write_text("{}", encoding="utf-8")
    (source / "adapter_model.safetensors").write_bytes(b"weights")
    env_file = tmp_path / ".env.madlad.docker"
    env_file.write_text(f"MADLAD_WEIGHTS_SOURCE_PATH={source}\n", encoding="utf-8")
    monkeypatch.delenv("MADLAD_WEIGHTS_SOURCE_PATH", raising=False)
    dest = tmp_path / "madlad" / "es"

    exit_code = _MODULE.main(
        ["--env-file", str(env_file), "--lang", "es", "--dest", str(dest)]
    )

    assert exit_code == 0
    assert dest == tmp_path / "madlad" / "es"
    assert (dest / "adapter_model.safetensors").is_file()
    assert _MODULE.DEFAULT_ADAPTERS_ROOT.name == "madlad"
    assert _MODULE.DEFAULT_LANG == "fa"
