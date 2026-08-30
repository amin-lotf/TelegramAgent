from __future__ import annotations

import hashlib
import hmac
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
    webhook_url="https://n8n.example.com/",
    telegram_verify_password="verify-secret-password",
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
        webhook_url="https://n8n.example.com/",
        telegram_verify_password="verify-secret-password",
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


def test_webhook_url_is_written_to_n8n_env(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/n8n/.env.n8n.docker.example",
        "WEBHOOK_URL=\nN8N_EDITOR_BASE_URL=https://ops.com/\nN8N_ENCRYPTION_KEY=replace-me\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    values = _env(tmp_path / "docker/n8n/.env.n8n.docker")
    assert values["WEBHOOK_URL"] == "https://n8n.example.com/"
    assert values["N8N_EDITOR_BASE_URL"] == "https://ops.com/"
    assert values["N8N_ENCRYPTION_KEY"] != "replace-me"


def test_bot_verify_hash_is_hmac_of_chosen_password(tmp_path: Path) -> None:
    password = "verify-secret-password"
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "BOT_VERIFY_HASH=replace-me\nBOT_VERIFY_SECRET=replace-me\nAUTH_SERVICE_TOKEN=replace-me\n",
    )

    _MODULE.setup_env_files(tmp_path, CREDENTIALS)

    dest = tmp_path / "docker/app/.env.telegram_auth.docker"
    contents = dest.read_text(encoding="utf-8")
    values = _env(dest)
    assert password not in contents
    assert values["BOT_VERIFY_SECRET"] not in {password, "replace-me", ""}
    expected = hmac.new(
        values["BOT_VERIFY_SECRET"].encode("utf-8"),
        password.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    assert values["BOT_VERIFY_HASH"] == expected
    assert values["BOT_VERIFY_HASH"] != "replace-me"


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
        "WEBHOOK_URL",
        "TELEGRAM_VERIFY_PASSWORD",
        "HF_TOKEN",
        "ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_non_interactive_missing_webhook_url_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/n8n/.env.n8n.docker.example",
        "WEBHOOK_URL=\n",
    )
    dest = example.with_name(".env.n8n.docker")
    monkeypatch.setenv("HF_TOKEN", "hf-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-from-env")
    monkeypatch.setenv("TELEGRAM_API_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash-from-env")
    monkeypatch.setenv("TELEGRAM_VERIFY_PASSWORD", "verify-from-env")
    monkeypatch.delenv("WEBHOOK_URL", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_non_interactive_missing_verify_password_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "BOT_VERIFY_HASH=replace-me\nBOT_VERIFY_SECRET=replace-me\n",
    )
    dest = example.with_name(".env.telegram_auth.docker")
    monkeypatch.setenv("HF_TOKEN", "hf-from-env")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-from-env")
    monkeypatch.setenv("TELEGRAM_API_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash-from-env")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com/")
    monkeypatch.delenv("TELEGRAM_VERIFY_PASSWORD", raising=False)

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
    _write_example(
        tmp_path,
        "docker/n8n/.env.n8n.docker.example",
        "WEBHOOK_URL=\n",
    )
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "BOT_VERIFY_HASH=replace-me\nBOT_VERIFY_SECRET=replace-me\n",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-from-env")
    monkeypatch.setenv("TELEGRAM_API_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash-from-env")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com/")
    monkeypatch.setenv("TELEGRAM_VERIFY_PASSWORD", "verify-from-env")
    monkeypatch.setenv("HF_TOKEN", "hf-from-env")
    monkeypatch.delenv("DOWNLOAD_AGENT_BACKEND", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 0
    assert _env(tmp_path / "docker/app/.env.llm_gateway.docker")["OPENAI_API_KEY"] == "sk-from-env"
    assert _env(tmp_path / "docker/app/.env.llm_gateway.docker")["TELEGRAM_BOT_TOKEN"] == "bot-from-env"
    assert _env(tmp_path / "docker/telegram_bot_api/.env.telegram_bot_api.docker")["TELEGRAM_API_ID"] == "42"
    assert _env(tmp_path / "docker/n8n/.env.n8n.docker")["WEBHOOK_URL"] == "https://hooks.example.com/"
    auth = _env(tmp_path / "docker/app/.env.telegram_auth.docker")
    expected_hash = hmac.new(
        auth["BOT_VERIFY_SECRET"].encode("utf-8"),
        b"verify-from-env",
        hashlib.sha256,
    ).hexdigest()
    assert auth["BOT_VERIFY_HASH"] == expected_hash
    assert "verify-from-env" not in (
        tmp_path / "docker/app/.env.telegram_auth.docker"
    ).read_text(encoding="utf-8")
    assert _env(tmp_path / "docker/admin_dashboard/.env.admin_dashboard.docker")["ADMIN_PASSWORD"] == "admin"
    output = capsys.readouterr().out
    assert "✓ Hugging Face configured" in output
    assert "✓ OpenAI configured for download requests" in output
    assert "✓ n8n webhook configured" in output
    assert "✓ Telegram user verification configured" in output
    assert "○ Hugging Face disabled" not in output
    assert "Run: make build" in output
    assert "make download-models" in output
    assert "     make up openai" in output
    assert "Build Docker images now?" not in output


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_TOKEN", "hf-from-env")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "bot-from-env")
    monkeypatch.setenv("TELEGRAM_API_ID", "42")
    monkeypatch.setenv("TELEGRAM_API_HASH", "hash-from-env")
    monkeypatch.setenv("WEBHOOK_URL", "https://hooks.example.com/")
    monkeypatch.setenv("TELEGRAM_VERIFY_PASSWORD", "verify-from-env")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)


def test_non_interactive_missing_hf_token_fails_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.gpu_execution.docker.example",
        "HF_TOKEN=\nWHISPERX_HF_TOKEN=\n",
    )
    dest = example.with_name(".env.gpu_execution.docker")
    _set_required_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.delenv("HF_TOKEN", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_non_interactive_local_backend_skips_openai_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nDOWNLOAD_AGENT_BACKEND=openai\n",
    )
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "BOT_VERIFY_HASH=replace-me\nBOT_VERIFY_SECRET=replace-me\n",
    )
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DOWNLOAD_AGENT_BACKEND", "local")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 0
    values = _env(tmp_path / "docker/app/.env.llm_gateway.docker")
    assert values["DOWNLOAD_AGENT_BACKEND"] == "local"
    assert values["OPENAI_API_KEY"] == ""
    output = capsys.readouterr().out
    assert "✓ Local model configured for download requests" in output
    assert "✓ Hugging Face configured" in output
    assert "     make up" in output
    assert "make up openai" not in output
    assert "Build Docker images now?" not in output


def test_non_interactive_openai_backend_requires_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nDOWNLOAD_AGENT_BACKEND=openai\n",
    )
    dest = example.with_name(".env.llm_gateway.docker")
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DOWNLOAD_AGENT_BACKEND", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_non_interactive_invalid_backend_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    example = _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "DOWNLOAD_AGENT_BACKEND=openai\n",
    )
    dest = example.with_name(".env.llm_gateway.docker")
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DOWNLOAD_AGENT_BACKEND", "cloud")

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 1
    assert not dest.exists()


def test_interactive_local_choice_does_not_ask_for_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getpass(prompt: str) -> str:
        if "Hugging Face" in prompt:
            return "hf_token"
        if "OpenAI" in prompt:
            raise AssertionError("OpenAI key must not be requested for local setup")
        if "bot token" in prompt:
            return "123:bot-token"
        if "API ID" in prompt:
            return "111111"
        if "API hash" in prompt:
            return "api-hash"
        if "verification password" in prompt:
            return "verify-secret-password"
        if "Admin password" in prompt:
            return ""
        raise AssertionError(prompt)

    choices = iter(["nope", "1"])

    def fake_input(prompt: str) -> str:
        if "Choice" in prompt:
            return next(choices)
        if "webhook" in prompt.lower() or "n8n" in prompt.lower():
            return "https://n8n.example.com/"
        raise AssertionError(prompt)

    monkeypatch.setattr(_MODULE.getpass, "getpass", fake_getpass)
    monkeypatch.setattr("builtins.input", fake_input)

    credentials = _MODULE.collect_credentials(interactive=True)

    assert credentials.hf_token == "hf_token"
    assert credentials.download_agent_backend == "local"
    assert credentials.openai_api_key == ""
    assert credentials.admin_password == "admin"


def test_interactive_openai_choice_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getpass(prompt: str) -> str:
        if "Hugging Face" in prompt:
            return "hf_token"
        if "OpenAI" in prompt:
            return "sk-live"
        if "bot token" in prompt:
            return "123:bot-token"
        if "API ID" in prompt:
            return "111111"
        if "API hash" in prompt:
            return "api-hash"
        if "verification password" in prompt:
            return "verify-secret-password"
        if "Admin password" in prompt:
            return "secret-admin"
        raise AssertionError(prompt)

    def fake_input(prompt: str) -> str:
        if "Choice" in prompt:
            return "2"
        if "webhook" in prompt.lower() or "n8n" in prompt.lower():
            return "https://n8n.example.com/"
        raise AssertionError(prompt)

    monkeypatch.setattr(_MODULE.getpass, "getpass", fake_getpass)
    monkeypatch.setattr("builtins.input", fake_input)

    credentials = _MODULE.collect_credentials(interactive=True)

    assert credentials.download_agent_backend == "openai"
    assert credentials.openai_api_key == "sk-live"
    assert credentials.admin_password == "secret-admin"


def test_setup_writes_download_agent_backend(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nDOWNLOAD_AGENT_BACKEND=openai\n",
    )
    _write_example(
        tmp_path,
        "docker/app/.env.content_processing.docker.example",
        "SUBTITLE_TRANSLATION_BACKEND=openai\n",
    )
    credentials = _MODULE.UserCredentials(
        openai_api_key="",
        telegram_bot_token="123:bot-token",
        telegram_api_id="111111",
        telegram_api_hash="api-hash",
        webhook_url="https://n8n.example.com/",
        telegram_verify_password="verify-secret-password",
        hf_token="hf_test_token",
        download_agent_backend="local",
    )

    _MODULE.setup_env_files(tmp_path, credentials)

    values = _env(tmp_path / "docker/app/.env.llm_gateway.docker")
    assert values["DOWNLOAD_AGENT_BACKEND"] == "local"
    assert values["OPENAI_API_KEY"] == ""
    translation = _env(tmp_path / "docker/app/.env.content_processing.docker")
    assert translation["SUBTITLE_TRANSLATION_BACKEND"] == "local"


def _write_configured_env(root: Path, relative: str, contents: str) -> Path:
    dest = _write_example(root, relative, contents)
    example = dest.with_name(dest.name + ".example")
    example.write_text(contents, encoding="utf-8")
    return dest


def _backend_env_tree(tmp_path: Path, *, openai_key: str, backend: str) -> tuple[Path, Path]:
    gateway = _write_configured_env(
        tmp_path,
        "docker/app/.env.llm_gateway.docker",
        (
            f"OPENAI_API_KEY={openai_key}\n"
            f"DOWNLOAD_AGENT_BACKEND={backend}\n"
            "LLM_GATEWAY_SERVICE_TOKEN=already-generated\n"
        ),
    )
    translation = _write_configured_env(
        tmp_path,
        "docker/app/.env.content_processing.docker",
        (
            f"SUBTITLE_TRANSLATION_BACKEND={backend}\n"
            "CONTENT_PROCESSING_SERVICE_TOKEN=already-generated\n"
        ),
    )
    return gateway, translation


def test_apply_backend_local_keeps_openai_key_and_generated_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="sk-existing", backend="openai"
    )

    def fake_getpass(prompt: str) -> str:
        raise AssertionError("OpenAI key must not be requested for local backend")

    monkeypatch.setattr(_MODULE.getpass, "getpass", fake_getpass)

    _MODULE.apply_backend(tmp_path, "local", interactive=True)

    values = _env(gateway)
    assert values["DOWNLOAD_AGENT_BACKEND"] == "local"
    assert values["OPENAI_API_KEY"] == "sk-existing"
    assert values["LLM_GATEWAY_SERVICE_TOKEN"] == "already-generated"
    translation_values = _env(translation)
    assert translation_values["SUBTITLE_TRANSLATION_BACKEND"] == "local"
    assert translation_values["CONTENT_PROCESSING_SERVICE_TOKEN"] == "already-generated"


def test_apply_backend_openai_reuses_existing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="sk-existing", backend="local"
    )

    def fake_getpass(prompt: str) -> str:
        raise AssertionError("OpenAI key must not be requested when one already exists")

    monkeypatch.setattr(_MODULE.getpass, "getpass", fake_getpass)

    _MODULE.apply_backend(tmp_path, "openai", interactive=True)

    assert _env(gateway)["DOWNLOAD_AGENT_BACKEND"] == "openai"
    assert _env(gateway)["OPENAI_API_KEY"] == "sk-existing"
    assert _env(translation)["SUBTITLE_TRANSLATION_BACKEND"] == "openai"


def test_apply_backend_openai_prompts_when_key_is_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="replace-me", backend="local"
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_MODULE.getpass, "getpass", lambda prompt: "sk-live")

    _MODULE.apply_backend(tmp_path, "openai", interactive=True)

    assert _env(gateway)["OPENAI_API_KEY"] == "sk-live"
    assert _env(gateway)["DOWNLOAD_AGENT_BACKEND"] == "openai"
    assert _env(translation)["SUBTITLE_TRANSLATION_BACKEND"] == "openai"


def test_apply_backend_openai_prompts_when_key_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, _translation = _backend_env_tree(
        tmp_path, openai_key="", backend="local"
    )
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_MODULE.getpass, "getpass", lambda prompt: "sk-from-prompt")

    _MODULE.apply_backend(tmp_path, "openai", interactive=True)

    assert _env(gateway)["OPENAI_API_KEY"] == "sk-from-prompt"


def test_apply_backend_openai_interactive_without_tty_does_not_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="", backend="local"
    )
    original_gateway = gateway.read_text(encoding="utf-8")
    original_translation = translation.read_text(encoding="utf-8")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

    with pytest.raises(_MODULE.SetupError, match="terminal"):
        _MODULE.apply_backend(tmp_path, "openai", interactive=True)

    assert gateway.read_text(encoding="utf-8") == original_gateway
    assert translation.read_text(encoding="utf-8") == original_translation


def test_apply_backend_openai_non_interactive_requires_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="replace-me", backend="local"
    )
    original_gateway = gateway.read_text(encoding="utf-8")
    original_translation = translation.read_text(encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = _MODULE.main(
        ["--root", str(tmp_path), "--apply-backend", "openai", "--non-interactive"]
    )

    assert exit_code == 1
    assert gateway.read_text(encoding="utf-8") == original_gateway
    assert translation.read_text(encoding="utf-8") == original_translation


def test_apply_backend_openai_non_interactive_reads_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="", backend="local"
    )
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")

    exit_code = _MODULE.main(
        ["--root", str(tmp_path), "--apply-backend", "openai", "--non-interactive"]
    )

    assert exit_code == 0
    assert _env(gateway)["OPENAI_API_KEY"] == "sk-from-env"
    assert _env(gateway)["DOWNLOAD_AGENT_BACKEND"] == "openai"
    assert _env(translation)["SUBTITLE_TRANSLATION_BACKEND"] == "openai"
    assert "Using OpenAI" in capsys.readouterr().out


def test_apply_backend_local_via_main(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gateway, translation = _backend_env_tree(
        tmp_path, openai_key="sk-existing", backend="openai"
    )

    exit_code = _MODULE.main(["--root", str(tmp_path), "--apply-backend", "local"])

    assert exit_code == 0
    assert _env(gateway)["DOWNLOAD_AGENT_BACKEND"] == "local"
    assert _env(gateway)["OPENAI_API_KEY"] == "sk-existing"
    assert _env(translation)["SUBTITLE_TRANSLATION_BACKEND"] == "local"
    assert "Using local GPU" in capsys.readouterr().out


def test_apply_backend_missing_env_files_fails(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "DOWNLOAD_AGENT_BACKEND=openai\nOPENAI_API_KEY=replace-me\n",
    )

    with pytest.raises(_MODULE.SetupError, match="make setup"):
        _MODULE.apply_backend(tmp_path, "local", interactive=False)


def test_apply_backend_rejects_invalid_backend(tmp_path: Path) -> None:
    _backend_env_tree(tmp_path, openai_key="sk-existing", backend="local")

    with pytest.raises(_MODULE.SetupError, match="local"):
        _MODULE.apply_backend(tmp_path, "cloud", interactive=False)


def test_apply_backend_invalid_choice_is_rejected_by_argparse() -> None:
    with pytest.raises(SystemExit) as exc:
        _MODULE.main(["--apply-backend", "cloud"])
    assert exc.value.code == 2


def _write_setup_examples(tmp_path: Path) -> None:
    _write_example(
        tmp_path,
        "docker/app/.env.llm_gateway.docker.example",
        "OPENAI_API_KEY=replace-me\nDOWNLOAD_AGENT_BACKEND=openai\n",
    )
    _write_example(
        tmp_path,
        "docker/n8n/.env.n8n.docker.example",
        "WEBHOOK_URL=\n",
    )
    _write_example(
        tmp_path,
        "docker/app/.env.telegram_auth.docker.example",
        "BOT_VERIFY_HASH=replace-me\nBOT_VERIFY_SECRET=replace-me\n",
    )


def _interactive_getpass(*, openai_key: str | None = "sk-live"):
    def fake_getpass(prompt: str) -> str:
        if "Hugging Face" in prompt:
            return "hf_token"
        if "OpenAI" in prompt:
            if openai_key is None:
                raise AssertionError("OpenAI key must not be requested")
            return openai_key
        if "bot token" in prompt:
            return "123:bot-token"
        if "API ID" in prompt:
            return "111111"
        if "API hash" in prompt:
            return "api-hash"
        if "verification password" in prompt:
            return "verify-secret-password"
        if "Admin password" in prompt:
            return ""
        raise AssertionError(prompt)

    return fake_getpass


def _patch_input(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    remaining = list(answers)

    def fake_input(prompt: str) -> str:
        if not remaining:
            raise AssertionError(f"Unexpected input prompt: {prompt!r}")
        return remaining.pop(0)

    monkeypatch.setattr("builtins.input", fake_input)
    return remaining


def _patch_make(
    monkeypatch: pytest.MonkeyPatch, codes: list[int] | None = None
) -> list[list[str]]:
    calls: list[list[str]] = []
    remaining = list(codes or [])

    def fake_run(command, cwd=None, check=False):
        del cwd, check
        calls.append(list(command))
        code = remaining.pop(0) if remaining else 0

        class Result:
            returncode = code

        return Result()

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)
    return calls


def _prepare_interactive_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    answers: list[str],
    openai_key: str | None = "sk-live",
    make_codes: list[int] | None = None,
) -> tuple[list[str], list[list[str]]]:
    _write_setup_examples(tmp_path)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(_MODULE.getpass, "getpass", _interactive_getpass(openai_key=openai_key))
    remaining = _patch_input(monkeypatch, answers)
    calls = _patch_make(monkeypatch, make_codes)
    return remaining, calls


def test_non_interactive_does_not_run_make(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_setup_examples(tmp_path)
    _set_required_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    monkeypatch.delenv("DOWNLOAD_AGENT_BACKEND", raising=False)

    def fake_run(*args, **kwargs):
        raise AssertionError("non-interactive setup must not run make")

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)

    exit_code = _MODULE.main(["--root", str(tmp_path), "--non-interactive"])

    assert exit_code == 0


def test_interactive_decline_build_prints_later_commands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["2", "https://n8n.example.com/", "n"],
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert remaining == []
    assert calls == []
    output = capsys.readouterr().out
    assert "Configuration completed." in output
    assert "Build Docker images now?" in output
    assert "You can also run this later with: make build" in output
    assert "You can run these later:" in output
    assert "  make build" in output
    assert "  make download-models" in output
    assert "  make up openai" in output
    assert "Download GPU model weights now?" not in output
    assert "Start the stack now?" not in output


def test_interactive_yes_build_failure_skips_download_and_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["2", "https://n8n.example.com/", "y"],
        make_codes=[1],
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 1
    assert remaining == []
    assert calls == [["make", "build"]]
    captured = capsys.readouterr()
    assert "Build failed. You can retry later with: make build" in captured.err
    assert "  make download-models" in captured.out
    assert "Download GPU model weights now?" not in captured.out
    assert "Start the stack now?" not in captured.out


def test_interactive_yes_build_skip_models_and_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["2", "https://n8n.example.com/", "y", "n", "n"],
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert remaining == []
    assert calls == [["make", "build"]]
    output = capsys.readouterr().out
    assert "Running: make build" in output
    assert "Download GPU model weights now?" in output
    assert "Start the stack now?" in output
    assert "  make download-models" in output
    assert "  make up openai" in output
    assert "  make build" not in output


def test_interactive_full_chain_openai_runs_up_openai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["2", "https://n8n.example.com/", "y", "y", "y"],
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert remaining == []
    assert calls == [
        ["make", "build"],
        ["make", "download-models"],
        ["make", "up", "openai"],
    ]


def test_interactive_full_chain_local_runs_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["1", "https://n8n.example.com/", "y", "y", "y"],
        openai_key=None,
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 0
    assert remaining == []
    assert calls == [
        ["make", "build"],
        ["make", "download-models"],
        ["make", "up"],
    ]
    output = capsys.readouterr().out
    assert "You can also run this later with: make up" in output
    assert "make up openai" not in output


def test_interactive_download_failure_still_offers_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    remaining, calls = _prepare_interactive_setup(
        tmp_path,
        monkeypatch,
        answers=["2", "https://n8n.example.com/", "y", "y", "y"],
        make_codes=[0, 2, 0],
    )

    exit_code = _MODULE.main(["--root", str(tmp_path)])

    assert exit_code == 1
    assert remaining == []
    assert calls == [
        ["make", "build"],
        ["make", "download-models"],
        ["make", "up", "openai"],
    ]
    captured = capsys.readouterr()
    assert "Model download failed" in captured.err
    assert "make download-models" in captured.out


def test_apply_backend_does_not_offer_followup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _backend_env_tree(tmp_path, openai_key="sk-existing", backend="openai")

    def fake_run(*args, **kwargs):
        raise AssertionError("apply-backend must not run make")

    monkeypatch.setattr(_MODULE.subprocess, "run", fake_run)
    monkeypatch.setattr("builtins.input", lambda prompt: (_ for _ in ()).throw(
        AssertionError(f"apply-backend must not prompt: {prompt!r}")
    ))

    exit_code = _MODULE.main(["--root", str(tmp_path), "--apply-backend", "local"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Using local GPU" in output
    assert "Build Docker images now?" not in output


def test_prompt_yes_no_rejects_invalid_then_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remaining = _patch_input(monkeypatch, ["maybe", "Y"])

    assert _MODULE._prompt_yes_no("Build Docker images now?", "make build") is True
    assert remaining == []


def test_is_generated_secret_does_not_match_token_count_settings() -> None:
    assert _MODULE.is_generated_secret("AUTH_SERVICE_TOKEN")
    assert _MODULE.is_generated_secret("N8N_ENCRYPTION_KEY")
    assert _MODULE.is_generated_secret("SESSION_SECRET")
    assert not _MODULE.is_generated_secret("MADLAD_MAX_NEW_TOKENS")
    assert not _MODULE.is_generated_secret("COORDINATION_MAX_OUTPUT_TOKENS")
    assert not _MODULE.is_generated_secret("OPENAI_API_KEY")
    assert not _MODULE.is_generated_secret("TELEGRAM_BOT_TOKEN")
    assert not _MODULE.is_generated_secret("ADMIN_PASSWORD")
    assert not _MODULE.is_generated_secret("WEBHOOK_URL")
    assert not _MODULE.is_generated_secret("BOT_VERIFY_SECRET")
    assert not _MODULE.is_generated_secret("BOT_VERIFY_HASH")
    assert not _MODULE.is_generated_secret("DB_POSTGRESDB_PASSWORD")
