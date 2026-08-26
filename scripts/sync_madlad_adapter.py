#!/usr/bin/env python3
"""Copy inference-only MADLAD LoRA files into TelegramAgent.

The default source is read from docker/madlad/.env.madlad.docker and falls
back to the sibling LanguageTranslator export. Relative paths are resolved
from the TelegramAgent repository root. The default destination is
pretrained_models/madlad/<lang> (lang defaults to fa). The source is never
modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = REPO_ROOT / "docker" / "madlad" / ".env.madlad.docker"
DEFAULT_SOURCE = (
    REPO_ROOT.parent
    / "LanguageTranslator"
    / "src"
    / "language_translator"
    / "runners"
    / "training"
    / "madlad-qlora-adapter"
)
DEFAULT_ADAPTERS_ROOT = REPO_ROOT / "pretrained_models" / "madlad"
DEFAULT_LANG = "fa"
REQUIRED_FILES = ("adapter_config.json", "adapter_model.safetensors")
OPTIONAL_FILES = ("tokenizer.json", "tokenizer_config.json")
_HASH_CHUNK_SIZE = 1024 * 1024


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid env line {line_number} in {path}")
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[7:].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _resolve_from_repo(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_adapter(*, source: Path, dest: Path) -> Path:
    source = source.expanduser().resolve()
    dest = dest.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"Adapter source directory not found: {source}")
    missing = [name for name in REQUIRED_FILES if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(
            f"Adapter source {source} is missing: {', '.join(missing)}"
        )

    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in REQUIRED_FILES + OPTIONAL_FILES:
        source_file = source / name
        if source_file.is_file():
            shutil.copy2(source_file, dest / name)
            copied.append(name)

    meta = {
        "source": str(source),
        "copied_files": copied,
        "sha256": _sha256_file(dest / "adapter_model.safetensors"),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }
    (dest / "adapter_meta.json").write_text(
        json.dumps(meta, indent=2) + "\n", encoding="utf-8"
    )
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--lang",
        default=DEFAULT_LANG,
        help="Target language code for the destination directory (default: fa)",
    )
    parser.add_argument("--dest", type=Path)
    args = parser.parse_args(argv)

    try:
        env_values = _read_env_file(args.env_file)
        configured_source = (
            args.source
            or Path(
                os.environ.get("MADLAD_WEIGHTS_SOURCE_PATH")
                or env_values.get("MADLAD_WEIGHTS_SOURCE_PATH")
                or DEFAULT_SOURCE
            )
        )
        source = _resolve_from_repo(configured_source)
        lang = (args.lang or DEFAULT_LANG).strip() or DEFAULT_LANG
        dest = _resolve_from_repo(
            args.dest if args.dest is not None else DEFAULT_ADAPTERS_ROOT / lang
        )
        synced = sync_adapter(source=source, dest=dest)
    except (FileNotFoundError, PermissionError, OSError, ValueError) as exc:
        print(f"MADLAD adapter sync failed: {exc}", file=sys.stderr)
        return 1

    print(f"Synced MADLAD adapter to {synced}")
    print((synced / "adapter_meta.json").read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
