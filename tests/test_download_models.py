from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_models.py"
_SPEC = importlib.util.spec_from_file_location("fatol_download_models", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_hf_snapshot(
    cache_root: Path, repo_id: str, *, incomplete: bool = False
) -> None:
    repo_dir = cache_root / "hub" / f"models--{repo_id.replace('/', '--')}"
    (repo_dir / "refs").mkdir(parents=True)
    (repo_dir / "refs" / "main").write_text("abc123\n", encoding="utf-8")
    snapshot = repo_dir / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")
    blobs = repo_dir / "blobs"
    blobs.mkdir()
    (blobs / "hash").write_bytes(b"data")
    if incomplete:
        (blobs / "hash.incomplete").write_bytes(b"partial")


def _complete_all(locations: _MODULE.Locations) -> None:
    locations.cosyvoice_dir.mkdir(parents=True)
    (locations.cosyvoice_dir / "cosyvoice3.yaml").write_text("ok\n", encoding="utf-8")
    locations.imagebind_path.parent.mkdir(parents=True)
    locations.imagebind_path.write_bytes(b"x" * 16)
    for asset in _MODULE.assets():
        if asset.kind != "hf" or not asset.repo_id:
            continue
        _write_hf_snapshot(_MODULE.cache_root_for(asset, locations), asset.repo_id)


class FakeDownloader:
    def __init__(
        self,
        *,
        gated: tuple[str, ...] = (),
        fail: tuple[str, ...] = (),
    ) -> None:
        self.gated = set(gated)
        self.fail = set(fail)
        self.snapshots: list[str] = []
        self.http: list[str] = []

    def snapshot(
        self,
        repo_id: str,
        *,
        cache_dir: Path | None = None,
        local_dir: Path | None = None,
        token: str | None = None,
    ) -> None:
        self.snapshots.append(repo_id)
        if repo_id in self.gated:
            raise _MODULE.GatedDownloadError(repo_id)
        if repo_id in self.fail:
            raise _MODULE.DownloadModelsError(f"failed {repo_id}")
        if local_dir is not None:
            local_dir.mkdir(parents=True, exist_ok=True)
            (local_dir / "cosyvoice3.yaml").write_text("ok\n", encoding="utf-8")
        if cache_dir is not None:
            _write_hf_snapshot(cache_dir, repo_id)

    def http_file(self, url: str, dest: Path) -> None:
        self.http.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * _MODULE.imagebind_min_bytes())


@pytest.fixture
def min_imagebind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGEBIND_MIN_BYTES", "16")


def test_skips_complete_cosyvoice(tmp_path: Path) -> None:
    model_dir = tmp_path / "Fun-CosyVoice3-0.5B"
    model_dir.mkdir()
    (model_dir / "cosyvoice3.yaml").write_text("ok\n", encoding="utf-8")
    assert _MODULE.cosyvoice_complete(model_dir)
    assert not _MODULE.cosyvoice_complete(tmp_path / "missing")


def test_skips_large_imagebind_and_rejects_tiny(
    tmp_path: Path, min_imagebind: None
) -> None:
    path = tmp_path / "imagebind_huge.pth"
    path.write_bytes(b"tiny")
    assert not _MODULE.imagebind_complete(path)
    path.write_bytes(b"x" * 16)
    assert _MODULE.imagebind_complete(path)


def test_hf_snapshot_complete_and_incomplete(tmp_path: Path) -> None:
    repo = "google/madlad400-3b-mt"
    _write_hf_snapshot(tmp_path, repo)
    assert _MODULE.hf_snapshot_complete(tmp_path, repo)
    _write_hf_snapshot(tmp_path, "facebook/sam-audio-small", incomplete=True)
    assert not _MODULE.hf_snapshot_complete(tmp_path, "facebook/sam-audio-small")
    assert not _MODULE.hf_snapshot_complete(tmp_path, "Systran/faster-whisper-large-v3")


def test_execute_skips_complete_assets_without_downloading(
    tmp_path: Path, min_imagebind: None, capsys: pytest.CaptureFixture[str]
) -> None:
    locations = _MODULE.host_locations(tmp_path)
    _complete_all(locations)
    downloader = FakeDownloader()

    code = _MODULE.execute_downloads(locations, token="hf_test", downloader=downloader)

    assert code == 0
    assert downloader.snapshots == []
    assert downloader.http == []
    output = capsys.readouterr().out
    assert "skip CosyVoice" in output
    assert "skip ImageBind" in output
    assert "skip SAM Audio" in output


def test_execute_downloads_missing_public_and_imagebind(
    tmp_path: Path, min_imagebind: None
) -> None:
    locations = _MODULE.host_locations(tmp_path)
    downloader = FakeDownloader()

    code = _MODULE.execute_downloads(locations, token="hf_test", downloader=downloader)

    assert code == 0
    assert _MODULE.cosyvoice_model_id() in downloader.snapshots
    assert _MODULE.whisper_asr_repo_id() in downloader.snapshots
    assert _MODULE.madlad_model_id() in downloader.snapshots
    assert _MODULE.sam_audio_model_id() in downloader.snapshots
    assert _MODULE.diarization_repo_id() in downloader.snapshots
    assert downloader.http == [_MODULE.IMAGEBIND_URL]
    assert _MODULE.cosyvoice_complete(locations.cosyvoice_dir)
    assert _MODULE.imagebind_complete(locations.imagebind_path)


def test_execute_gated_error_prints_urls_and_rerun_hint(
    tmp_path: Path,
    min_imagebind: None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    locations = _MODULE.host_locations(tmp_path)
    downloader = FakeDownloader(gated=(_MODULE.sam_audio_model_id(),))

    code = _MODULE.execute_downloads(locations, token="hf_test", downloader=downloader)

    assert code == _MODULE.EXIT_ACTION_REQUIRED
    err = capsys.readouterr().err
    assert "https://huggingface.co/facebook/sam-audio-small" in err
    assert "make download-models" in err
    assert _MODULE.cosyvoice_complete(locations.cosyvoice_dir)
    assert _MODULE.diarization_repo_id() in downloader.snapshots


def test_persist_hf_token_updates_existing_keys_only(tmp_path: Path) -> None:
    env_path = tmp_path / "docker/app/.env.gpu_execution.docker"
    env_path.parent.mkdir(parents=True)
    env_path.write_text(
        "HF_TOKEN=\nWHISPERX_HF_TOKEN=\nGPU_EXECUTION_SERVICE_TOKEN=keep-me\n",
        encoding="utf-8",
    )
    other = tmp_path / "docker/n8n/.env.n8n.docker"
    other.parent.mkdir(parents=True)
    other.write_text("N8N_HOST=n8n\n", encoding="utf-8")

    written = _MODULE.persist_hf_token(tmp_path, "hf_new_token")

    assert env_path in written
    assert other not in written
    contents = env_path.read_text(encoding="utf-8")
    assert "HF_TOKEN=hf_new_token" in contents
    assert "WHISPERX_HF_TOKEN=hf_new_token" in contents
    assert "GPU_EXECUTION_SERVICE_TOKEN=keep-me" in contents
    assert other.read_text(encoding="utf-8") == "N8N_HOST=n8n\n"


def test_host_skips_compose_when_everything_is_present(
    tmp_path: Path, min_imagebind: None
) -> None:
    locations = _MODULE.host_locations(tmp_path)
    _complete_all(locations)
    called: list[object] = []

    def compose_runner(**kwargs: object) -> int:
        called.append(kwargs)
        return 0

    code = _MODULE.main(
        ["--root", str(tmp_path), "--non-interactive"],
        compose_runner=compose_runner,
    )

    assert code == 0
    assert called == []


def test_non_interactive_missing_token_still_downloads_public(
    tmp_path: Path,
    min_imagebind: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("WHISPERX_HF_TOKEN", raising=False)
    env_path = tmp_path / "docker/app/.env.gpu_execution.docker"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("HF_TOKEN=\nWHISPERX_HF_TOKEN=\n", encoding="utf-8")
    calls: list[dict[str, object]] = []

    def compose_runner(*, root: Path, token: str) -> int:
        calls.append({"root": root, "token": token})
        return 0

    code = _MODULE.main(
        ["--root", str(tmp_path), "--non-interactive"],
        compose_runner=compose_runner,
    )

    assert code == _MODULE.EXIT_ACTION_REQUIRED
    assert calls == [{"root": tmp_path.resolve(), "token": ""}]
    err = capsys.readouterr().err
    assert "Hugging Face token is required" in err
    assert "facebook/sam-audio-small" in err


def test_interactive_token_is_persisted_before_compose(
    tmp_path: Path,
    min_imagebind: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("WHISPERX_HF_TOKEN", raising=False)
    env_path = tmp_path / "docker/app/.env.gpu_execution.docker"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("HF_TOKEN=\nWHISPERX_HF_TOKEN=\n", encoding="utf-8")
    monkeypatch.setattr(_MODULE, "prompt_hf_token", lambda: "hf_prompted")
    calls: list[str] = []

    def compose_runner(*, root: Path, token: str) -> int:
        calls.append(token)
        return 0

    code = _MODULE.run_host(
        root=tmp_path,
        interactive=True,
        compose_runner=compose_runner,
    )

    assert code == 0
    assert calls == ["hf_prompted"]
    values = _MODULE.parse_env_file(env_path)
    assert values["HF_TOKEN"] == "hf_prompted"
    assert values["WHISPERX_HF_TOKEN"] == "hf_prompted"


def test_makefile_exposes_build_and_download_models() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "build:\n" in makefile
    assert "download-models:\n" in makefile
    assert "python3 scripts/download_models.py" in makefile
    assert "--profile dubbing-init --profile madlad build" in makefile
    assert "python3 scripts/download_models.py --non-interactive" in makefile


def test_init_service_runs_execute_and_mounts_madlad_cache() -> None:
    compose = (
        REPO_ROOT / "docker" / "app" / "gpu-execution-docker-compose.yml"
    ).read_text(encoding="utf-8")
    assert "python /app/scripts/download_models.py --execute" in compose
    assert (
        "../../pretrained_models/madlad-hf-cache:/opt/madlad-hf-cache" in compose
    )
    assert "download_cosyvoice_models.py" not in compose
    assert "download_sam_audio_model.py" not in compose
