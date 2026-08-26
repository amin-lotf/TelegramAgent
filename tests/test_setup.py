from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "setup.py"
_SPEC = importlib.util.spec_from_file_location("fatol_setup", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

CREDENTIALS = _MODULE.UserCredentials(
    openai_api_key="sk-test-openai",
    telegram_bot_token="123:bot-token",
    telegram_api_id="111111",
    telegram_api_hash="api-hash",
    hf_token="",
    admin_password="admin",
)


def _write_example(root: Path, relative: str, contents: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return path


def _env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value
    return values


def test_discovers_examples_and_writes_dest_without_example_suffix(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nLLM_GATEWAY_SERVICE_TOKEN=replace-me\n",
    )

    written = _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    dest = tmp_path / "docker/app/.env.llm_gateway.docker"
    assert written == [dest]
    assert dest.is_file()
    assert not dest.name.endswith(".example")
    values = _env(dest)
    assert values["OPENAI_API_KEY"] == "sk-test-openai"
    assert values["LLM_GATEWAY_SERVICE_TOKEN"] != "replace-me"
    assert values["LLM_GATEWAY_SERVICE_TOKEN"]


def test_overwrites_existing_destination(tmp_path: Path) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\n",
    )
    dest = example.with_name(".env.llm_gateway.docker")
    dest.write_text("OPENAI_API_KEY=old-key\nEXTRA=keep-me-not\n", encoding="utf-8")

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    contents = dest.read_text(encoding="utf-8")
    assert "old-key" not in contents
    assert "EXTRA" not in contents
    assert _env(dest)["OPENAI_API_KEY"] == "sk-test-openai"


def test_shared_service_tokens_are_identical_across_files(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "AUTH_SERVICE_TOKEN=replace-me\nBOT_VERIFY_SECRET=replace-me\n",
    )
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_ingress.docker.example",
        "AUTH_SERVICE_TOKEN=replace-me\nTELEGRAM_BOT_TOKEN=replace-me\n",
    )
    _write_example(
        tmp_path,
        "docker/n8n/.env.n8n.docker.example",
        "AUTH_SERVICE_TOKEN=replace-me\nN8N_ENCRYPTION_KEY=replace-me\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    auth = _env(tmp_path / "docker/app/.env.telegram_auth.docker")
    ingress = _env(tmp_path / "docker/app/.env.telegram_ingress.docker")
    n8n = _env(tmp_path / "docker/n8n/.env.n8n.docker")
    assert auth["AUTH_SERVICE_TOKEN"] == ingress["AUTH_SERVICE_TOKEN"] == n8n["AUTH_SERVICE_TOKEN"]
    assert auth["AUTH_SERVICE_TOKEN"] != "replace-me"
    assert n8n["N8N_ENCRYPTION_KEY"] != "replace-me"
    assert ingress["TELEGRAM_BOT_TOKEN"] == "123:bot-token"


def test_preserves_comments_and_non_secret_values(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/madlad/.env.madlad.docker.example",
        "# Copy this file\n\nMADLAD_MAX_NEW_TOKENS=256\nHF_TOKEN=\nSESSION_SECRET=CHANGE_ME_LONG_RANDOM\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    dest = tmp_path / "docker/madlad/.env.madlad.docker"
    contents = dest.read_text(encoding="utf-8")
    assert contents.startswith("# Copy this file\n\n")
    values = _env(dest)
    assert values["MADLAD_MAX_NEW_TOKENS"] == "256"
    assert values["HF_TOKEN"] == ""
    assert values["SESSION_SECRET"] != "CHANGE_ME_LONG_RANDOM"


def test_hugging_face_skip_leaves_related_keys_empty(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.gpu_execution.docker.example",
        "HF_TOKEN=\nWHISPERX_HF_TOKEN=\nGPU_EXECUTION_SERVICE_TOKEN=replace-me\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    values = _env(tmp_path / "docker/app/.env.gpu_execution.docker")
    assert values["HF_TOKEN"] == ""
    assert values["WHISPERX_HF_TOKEN"] == ""


def test_hugging_face_token_copied_to_whisperx_key(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.gpu_execution.docker.example",
        "HF_TOKEN=\nWHISPERX_HF_TOKEN=\n",
    )
    credentials = _MODULE.UserCredentials(
        openai_api_key="sk-test-openai",
        telegram_bot_token="123:bot-token",
        telegram_api_id="111111",
        telegram_api_hash="api-hash",
        hf_token="hf_test_token",
        admin_password="admin",
    )

    _MODULE.setup_env_files(tmp_path, credentials)

    values = _env(tmp_path / "docker/app/.env.gpu_execution.docker")
    assert values["HF_TOKEN"] == "hf_test_token"
    assert values["WHISPERX_HF_TOKEN"] == "hf_test_token"


def test_admin_password_defaults_to_admin(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/admin_dashboard/.env.admin_dashboard.docker.example",
        "ADMIN_PASSWORD=CHANGE_ME\nSESSION_SECRET=CHANGE_ME_LONG_RANDOM\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    values = _env(tmp_path / "docker/admin_dashboard/.env.admin_dashboard.docker")
    assert values["ADMIN_PASSWORD"] == "admin"
    assert values["SESSION_SECRET"] != "CHANGE_ME_LONG_RANDOM"


def test_database_urls_with_change_me_are_not_rewritten(tmp_path: Path) -> None:
    url = "postgresql+asyncpg://dashboard_ro:CHANGE_ME@telegram_ingress_postgres:5432/telegram_agent"
    _write_example(
        tmp_path,
        "docker/admin_dashboard/.env.admin_dashboard.docker.example",
        f"TELEGRAM_INGRESS_RO_DATABASE_URL={url}\nADMIN_PASSWORD=CHANGE_ME\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    values = _env(tmp_path / "docker/admin_dashboard/.env.admin_dashboard.docker")
    assert values["TELEGRAM_INGRESS_RO_DATABASE_URL"] == url
    assert values["ADMIN_PASSWORD"] == "admin"


def test_empty_example_file_writes_empty_destination(tmp_path: Path) -> None:
    _write_example(tmp_path, "docker/storage/.env.storage.docker.example", "")

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    dest = tmp_path / "docker/storage/.env.storage.docker"
    assert dest.is_file()
    assert dest.read_text(encoding="utf-8") == ""


def test_non_interactive_missing_required_env_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\n",
    )
    dest = example.with_name(".env.llm_gateway.docker")
    for key in (
        "OPENAI_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "HF_TOKEN",
        "ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_non_interactive_reads_env_and_defaults_admin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nTELEGRAM_BOT_TOKEN=replace-me\n",
    )
    _write_example(
        tmp_path,
        "docker/admin_dashboard/.env.admin_dashboard.docker.example",
        "ADMIN_PASSWORD=CHANGE_ME\n",
    )
    _write_example(
        tmp_path,
        "docker/telegram_bot_api/.env.telegram_bot_api.docker.example",
        "TELEGRAM_API_ID=\nTELEGRAM_API_HASH=\n",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-from-env")
    monkeypatch.setenv("TELEGRAM_API_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash-from-env")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 0
    assert _env(tmp_path / "docker/app/.env.llm_gateway.docker")["OPENAI_API_KEY"] == "sk-from-env"
    assert _env(tmp_path / "docker/app/.env.llm_gateway.docker")["TELEGRAM_BOT_TOKEN"] == "bot-from-env"
    assert _env(tmp_path / "docker/telegram_bot_api/.env.telegram_bot_api.docker")["TELEGRAM_API_ID"] == "42"
    assert _env(tmp_path / "docker/admin_dashboard/.env.admin_dashboard.docker")["ADMIN_PASSWORD"] == "admin"
    output = capsys.readouterr().out
    assert "✓ OpenAI configured" in output
    assert "○ Hugging Face disabled" in output
    assert "Run: make build" in output
    assert "make download-models" in output
    assert "make up" in output


def test_is_generated_secret_does_not_match_token_count_settings() -> None:
    assert _MODULE.is_generated_secret("AUTH_SERVICE_TOKEN")
    assert _MODULE.is_generated_secret("N8N_ENCRYPTION_KEY")
    assert _MODULE.is_generated_secret("SESSION_SECRET")
    assert not _MODULE.is_generated_secret("MADLAD_MAX_NEW_TOKENS")
    assert not _MODULE.is_generated_secret("COORDINATION_MAX_OUTPUT_TOKENS")
    assert not _MODULE.is_generated_secret("OPENAI_API_KEY")
    assert not _MODULE.is_generated_secret("TELEGRAM_BOT_TOKEN")
    assert not _MODULE.is_generated_secret("ADMIN_PASSWORD")
    assert not _MODULE.is_generated_secret("DB_POSTGRESDB_PASSWORD")
