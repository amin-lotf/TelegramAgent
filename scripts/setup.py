#!/usr/bin/env python3
"""Create service .env files from examples and fill in credentials.

Copies every `.env.*.example` to `.env.*` (overwriting existing files),
generates shared internal tokens/secrets, and writes user-provided OpenAI,
Telegram, n8n webhook, Hugging Face, and admin-dashboard credentials.
Telegram user verification stores HMAC hash and secret, never the password.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import secrets
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

OPENAI_API_KEY = "OPENAI_API_KEY"
TELEGRAM_BOT_TOKEN = "TELEGRAM_BOT_TOKEN"
TELEGRAM_API_ID = "TELEGRAM_API_ID"
TELEGRAM_API_HASH = "TELEGRAM_API_HASH"
WEBHOOK_URL = "WEBHOOK_URL"
TELEGRAM_VERIFY_PASSWORD = "TELEGRAM_VERIFY_PASSWORD"
BOT_VERIFY_SECRET = "BOT_VERIFY_SECRET"
BOT_VERIFY_HASH = "BOT_VERIFY_HASH"
HF_TOKEN = "HF_TOKEN"
WHISPERX_HF_TOKEN = "WHISPERX_HF_TOKEN"
ADMIN_PASSWORD = "ADMIN_PASSWORD"
DOWNLOAD_AGENT_BACKEND = "DOWNLOAD_AGENT_BACKEND"
SUBTITLE_TRANSLATION_BACKEND = "SUBTITLE_TRANSLATION_BACKEND"

DEFAULT_ADMIN_PASSWORD = "admin"
DOWNLOAD_AGENT_BACKEND_LOCAL = "local"
DOWNLOAD_AGENT_BACKEND_OPENAI = "openai"
DEFAULT_DOWNLOAD_AGENT_BACKEND = DOWNLOAD_AGENT_BACKEND_OPENAI

USER_PROVIDED_KEYS = {
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_API_ID,
    TELEGRAM_API_HASH,
    WEBHOOK_URL,
    HF_TOKEN,
    WHISPERX_HF_TOKEN,
    ADMIN_PASSWORD,
    DOWNLOAD_AGENT_BACKEND,
    SUBTITLE_TRANSLATION_BACKEND,
}
GENERATED_EXACT_KEYS = {
    "N8N_CALLBACK_TOKEN",
    "SESSION_SECRET",
}

_PROMPT_LABELS = {
    OPENAI_API_KEY: "OpenAI API key",
    TELEGRAM_BOT_TOKEN: "Telegram bot token",
    TELEGRAM_API_ID: "Telegram API ID",
    TELEGRAM_API_HASH: "Telegram API hash",
    WEBHOOK_URL: "n8n webhook URL",
    TELEGRAM_VERIFY_PASSWORD: "Telegram verification password",
    HF_TOKEN: "Hugging Face token",
    ADMIN_PASSWORD: 'Admin password (optional, press Enter for "admin")',
}


class SetupError(Exception):
    """User-facing setup failure."""


@dataclass(frozen=True)
class UserCredentials:
    openai_api_key: str
    telegram_bot_token: str
    telegram_api_id: str
    telegram_api_hash: str
    webhook_url: str
    telegram_verify_password: str
    hf_token: str = ""
    admin_password: str = DEFAULT_ADMIN_PASSWORD
    download_agent_backend: str = DEFAULT_DOWNLOAD_AGENT_BACKEND

    def value_for(self, key: str) -> str:
        mapping = {
            OPENAI_API_KEY: self.openai_api_key,
            TELEGRAM_BOT_TOKEN: self.telegram_bot_token,
            TELEGRAM_API_ID: self.telegram_api_id,
            TELEGRAM_API_HASH: self.telegram_api_hash,
            WEBHOOK_URL: self.webhook_url,
            HF_TOKEN: self.hf_token,
            WHISPERX_HF_TOKEN: self.hf_token,
            ADMIN_PASSWORD: self.admin_password,
            DOWNLOAD_AGENT_BACKEND: self.download_agent_backend,
            SUBTITLE_TRANSLATION_BACKEND: self.download_agent_backend,
        }
        return mapping[key]


def generate_password_hash(password: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def bot_verify_values(password: str) -> dict[str, str]:
    secret = secrets.token_urlsafe(64)
    return {
        BOT_VERIFY_SECRET: secret,
        BOT_VERIFY_HASH: generate_password_hash(password, secret),
    }


def is_generated_secret(key: str) -> bool:
    if key in USER_PROVIDED_KEYS:
        return False
    if key.endswith("_SERVICE_TOKEN") or key.endswith("_ENCRYPTION_KEY"):
        return True
    return key in GENERATED_EXACT_KEYS


_SKIP_DIR_NAMES = {".git", ".venv", "__pycache__", "pretrained_models", "media"}


def discover_examples(root: Path) -> list[Path]:
    root = root.resolve()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIR_NAMES]
        for filename in filenames:
            if filename.startswith(".env.") and filename.endswith(".example"):
                found.append(Path(dirpath) / filename)
    return sorted(found)


def destination_for(example: Path) -> Path:
    if not example.name.endswith(".example"):
        raise ValueError(f"Not an example env file: {example}")
    return example.with_name(example.name[: -len(".example")])


def _parse_env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        return None
    key = line.split("=", 1)[0].strip()
    if key.startswith("export "):
        key = key[7:].strip()
    return key or None


def substitute_env_contents(text: str, values: dict[str, str]) -> str:
    if not text:
        return text
    output_lines: list[str] = []
    for raw_line in text.splitlines():
        key = _parse_env_key(raw_line)
        if key is None or key not in values:
            output_lines.append(raw_line)
            continue
        prefix = raw_line.split("=", 1)[0]
        output_lines.append(f"{prefix}={values[key]}")
    return "\n".join(output_lines) + "\n"


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def collect_generated_values(examples: list[Path]) -> dict[str, str]:
    generated: dict[str, str] = {}
    for example in examples:
        for raw_line in example.read_text(encoding="utf-8").splitlines():
            key = _parse_env_key(raw_line)
            if key is None or not is_generated_secret(key) or key in generated:
                continue
            generated[key] = secrets.token_urlsafe(64)
    return generated


def values_for_file(credentials: UserCredentials, generated: dict[str, str]) -> dict[str, str]:
    values = dict(generated)
    for key in USER_PROVIDED_KEYS:
        values[key] = credentials.value_for(key)
    values.update(bot_verify_values(credentials.telegram_verify_password))
    return values


def setup_env_files(root: Path, credentials: UserCredentials) -> list[Path]:
    examples = discover_examples(root)
    if not examples:
        raise SetupError(f"No .env.*.example files found under {root}")
    generated = collect_generated_values(examples)
    substitutions = values_for_file(credentials, generated)
    written: list[Path] = []
    for example in examples:
        dest = destination_for(example)
        contents = substitute_env_contents(
            example.read_text(encoding="utf-8"), substitutions
        )
        _write_atomic(dest, contents)
        written.append(dest)
    return written


def _read_required(name: str, *, interactive: bool, secret: bool = True) -> str:
    label = _PROMPT_LABELS[name]
    if interactive:
        prompt = f"{label}: "
        value = (getpass.getpass(prompt) if secret else input(prompt)).strip()
    else:
        value = os.environ.get(name, "").strip()
    if not value:
        if interactive:
            raise SetupError(f"{label} is required.")
        raise SetupError(f"{name} is required in non-interactive mode.")
    return value


def _read_optional(name: str, default: str, *, interactive: bool) -> str:
    label = _PROMPT_LABELS[name]
    if interactive:
        value = getpass.getpass(f"{label}: ").strip()
        return value if value else default
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip() or default


def _read_download_agent_backend(*, interactive: bool) -> str:
    if not interactive:
        raw = os.environ.get(
            DOWNLOAD_AGENT_BACKEND, DEFAULT_DOWNLOAD_AGENT_BACKEND
        ).strip().lower()
        if raw not in {
            DOWNLOAD_AGENT_BACKEND_LOCAL,
            DOWNLOAD_AGENT_BACKEND_OPENAI,
        }:
            raise SetupError(
                f"{DOWNLOAD_AGENT_BACKEND} must be "
                f"'{DOWNLOAD_AGENT_BACKEND_LOCAL}' or "
                f"'{DOWNLOAD_AGENT_BACKEND_OPENAI}'."
            )
        return raw

    print("How should the bot understand download requests and translate subtitles?")
    print()
    print("  [1] Local GPU — Qwen for requests, MADLAD for translation")
    print("      (no OpenAI key)")
    print("  [2] OpenAI — download requests plus glossary and")
    print("      subtitle translation")
    print()
    while True:
        choice = input("Choice [1/2]: ").strip()
        if choice == "1":
            return DOWNLOAD_AGENT_BACKEND_LOCAL
        if choice == "2":
            return DOWNLOAD_AGENT_BACKEND_OPENAI
        print("Please enter 1 or 2.")


def collect_credentials(*, interactive: bool) -> UserCredentials:
    hf_token = _read_required(HF_TOKEN, interactive=interactive)
    download_agent_backend = _read_download_agent_backend(interactive=interactive)
    if download_agent_backend == DOWNLOAD_AGENT_BACKEND_OPENAI:
        openai_api_key = _read_required(OPENAI_API_KEY, interactive=interactive)
    else:
        openai_api_key = ""
    return UserCredentials(
        openai_api_key=openai_api_key,
        telegram_bot_token=_read_required(TELEGRAM_BOT_TOKEN, interactive=interactive),
        telegram_api_id=_read_required(TELEGRAM_API_ID, interactive=interactive),
        telegram_api_hash=_read_required(TELEGRAM_API_HASH, interactive=interactive),
        webhook_url=_read_required(WEBHOOK_URL, interactive=interactive, secret=False),
        telegram_verify_password=_read_required(
            TELEGRAM_VERIFY_PASSWORD, interactive=interactive
        ),
        hf_token=hf_token,
        admin_password=_read_optional(
            ADMIN_PASSWORD, DEFAULT_ADMIN_PASSWORD, interactive=interactive
        ),
        download_agent_backend=download_agent_backend,
    )


def print_summary(credentials: UserCredentials) -> None:
    print("✓ Hugging Face configured")
    if credentials.download_agent_backend == DOWNLOAD_AGENT_BACKEND_OPENAI:
        print("✓ OpenAI configured for download requests and subtitle translation")
    else:
        print("✓ Local model configured for download requests and MADLAD translation")
    print("✓ Telegram configured")
    print("✓ Telegram API configured")
    print("✓ n8n webhook configured")
    print("✓ Telegram user verification configured")
    print("✓ Admin dashboard configured")
    print()
    print("Configuration completed.")
    print("Run: make build")
    print("     make download-models")
    print("     make up")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root that contains .env.*.example files.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help=(
            "Read credentials from environment variables instead of prompting. "
            "Required: HF_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_API_ID, "
            "TELEGRAM_API_HASH, WEBHOOK_URL, TELEGRAM_VERIFY_PASSWORD. "
            "OPENAI_API_KEY is required when DOWNLOAD_AGENT_BACKEND=openai "
            "(the default). That choice also selects OpenAI glossary and "
            "subtitle translation instead of MADLAD. Optional: "
            "DOWNLOAD_AGENT_BACKEND (openai|local), ADMIN_PASSWORD."
        ),
    )
    args = parser.parse_args(argv)
    interactive = not args.non_interactive
    if interactive and not sys.stdin.isatty():
        print(
            "Setup requires an interactive terminal, or pass --non-interactive "
            "with environment variables.",
            file=sys.stderr,
        )
        return 1

    try:
        if interactive:
            print("Fatol Assistant setup")
            print()
        credentials = collect_credentials(interactive=interactive)
        setup_env_files(args.root, credentials)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Setup failed: {exc}", file=sys.stderr)
        return 1

    if interactive:
        print()
    print_summary(credentials)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
