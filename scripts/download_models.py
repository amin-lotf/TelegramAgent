#!/usr/bin/env python3
"""Download GPU model weights used by Whisper, CosyVoice, SAM Audio, and MADLAD.

Host usage (default): skip complete caches, prompt for a Hugging Face token when
gated models remain, persist the token, then run the downloader inside the
gpu-execution-worker image.

Container usage: ``python3 scripts/download_models.py --execute``
"""

from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]

HF_TOKEN = "HF_TOKEN"
WHISPERX_HF_TOKEN = "WHISPERX_HF_TOKEN"
GPU_EXECUTION_ENV = Path("docker/app/.env.gpu_execution.docker")

DEFAULT_COSYVOICE_MODEL_ID = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
DEFAULT_COSYVOICE_MODEL_DIR = "/opt/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B"
DEFAULT_SAM_AUDIO_MODEL = "facebook/sam-audio-small"
DEFAULT_MADLAD_MODEL_ID = "google/madlad400-3b-mt"
DEFAULT_WHISPERX_MODEL = "large-v3"
DEFAULT_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"
IMAGEBIND_FILENAME = "imagebind_huge.pth"
IMAGEBIND_URL = "https://dl.fbaipublicfiles.com/imagebind/imagebind_huge.pth"
DEFAULT_IMAGEBIND_MIN_BYTES = 3 * 1024 * 1024 * 1024

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_ACTION_REQUIRED = 2

_SKIP_DIR_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "pretrained_models",
    "media",
    ".cache",
}


class DownloadModelsError(Exception):
    """User-facing download failure."""


class GatedDownloadError(Exception):
    def __init__(self, repo_id: str, message: str = "") -> None:
        self.repo_id = repo_id
        super().__init__(message or f"Gated Hugging Face repository: {repo_id}")


class HubDownloader(Protocol):
    def snapshot(
        self,
        repo_id: str,
        *,
        cache_dir: Path | None = None,
        local_dir: Path | None = None,
        token: str | None = None,
    ) -> None: ...

    def http_file(self, url: str, dest: Path) -> None: ...


@dataclass(frozen=True)
class Locations:
    hf_home: Path
    cosyvoice_dir: Path
    imagebind_path: Path
    madlad_hf_home: Path


@dataclass(frozen=True)
class Asset:
    key: str
    title: str
    gated: bool
    kind: str
    repo_id: str | None = None
    cache: str = "hf_home"


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def imagebind_min_bytes() -> int:
    raw = os.environ.get("IMAGEBIND_MIN_BYTES", "").strip()
    if raw.isdigit():
        return int(raw)
    return DEFAULT_IMAGEBIND_MIN_BYTES


def cosyvoice_model_id() -> str:
    return _env("COSYVOICE_MODEL_ID", DEFAULT_COSYVOICE_MODEL_ID)


def cosyvoice_model_dir_name() -> str:
    return Path(_env("COSYVOICE_MODEL_DIR", DEFAULT_COSYVOICE_MODEL_DIR)).name


def sam_audio_model_id() -> str:
    return _env("SAM_AUDIO_MODEL", DEFAULT_SAM_AUDIO_MODEL)


def madlad_model_id() -> str:
    return _env("MADLAD_MODEL_ID", DEFAULT_MADLAD_MODEL_ID)


def whisper_asr_repo_id() -> str:
    model = _env("WHISPERX_MODEL", DEFAULT_WHISPERX_MODEL)
    if "/" in model:
        return model
    return f"Systran/faster-whisper-{model}"


def diarization_repo_id() -> str:
    return _env("WHISPERX_DIARIZATION_MODEL", DEFAULT_DIARIZATION_MODEL)


def assets() -> list[Asset]:
    return [
        Asset("cosyvoice", "CosyVoice", False, "cosyvoice", cosyvoice_model_id()),
        Asset("whisper-asr", "Whisper ASR", False, "hf", whisper_asr_repo_id()),
        Asset(
            "madlad",
            "MADLAD",
            False,
            "hf",
            madlad_model_id(),
            cache="madlad_hf_home",
        ),
        Asset("imagebind", "ImageBind", False, "imagebind"),
        Asset("sam", "SAM Audio", True, "hf", sam_audio_model_id()),
        Asset(
            "whisper-diarization",
            "Whisper diarization",
            True,
            "hf",
            diarization_repo_id(),
        ),
    ]


def host_locations(root: Path) -> Locations:
    return Locations(
        hf_home=root / ".cache" / "huggingface",
        cosyvoice_dir=root / ".cache" / "cosyvoice" / cosyvoice_model_dir_name(),
        imagebind_path=(
            root
            / "pretrained_models"
            / "sam-audio-checkpoints"
            / IMAGEBIND_FILENAME
        ),
        madlad_hf_home=root / "pretrained_models" / "madlad-hf-cache",
    )


def execute_locations() -> Locations:
    hf_home = Path(
        _env("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
    )
    return Locations(
        hf_home=hf_home,
        cosyvoice_dir=Path(
            _env("COSYVOICE_MODEL_DIR", DEFAULT_COSYVOICE_MODEL_DIR)
        ),
        imagebind_path=Path(
            _env("SAM_AUDIO_CHECKPOINTS_DIR", "/app/.checkpoints")
        )
        / IMAGEBIND_FILENAME,
        madlad_hf_home=Path(
            _env("MADLAD_HF_HOME", str(hf_home))
        ),
    )


def hf_repo_cache_dir(cache_root: Path, repo_id: str) -> Path:
    return cache_root / "hub" / f"models--{repo_id.replace('/', '--')}"


def hf_snapshot_complete(cache_root: Path, repo_id: str) -> bool:
    repo_dir = hf_repo_cache_dir(cache_root, repo_id)
    revision = None
    for name in ("main", "master"):
        ref = repo_dir / "refs" / name
        if ref.is_file():
            revision = ref.read_text(encoding="utf-8").strip()
            if revision:
                break
    if not revision:
        return False
    snapshot = repo_dir / "snapshots" / revision
    if not snapshot.is_dir() or not any(snapshot.iterdir()):
        return False
    blobs = repo_dir / "blobs"
    if blobs.is_dir() and any(blobs.glob("*.incomplete")):
        return False
    return True


def cosyvoice_complete(model_dir: Path) -> bool:
    return (model_dir / "cosyvoice3.yaml").is_file()


def imagebind_complete(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= imagebind_min_bytes()
    except OSError:
        return False


def cache_root_for(asset: Asset, locations: Locations) -> Path:
    if asset.cache == "madlad_hf_home":
        return locations.madlad_hf_home
    return locations.hf_home


def is_complete(asset: Asset, locations: Locations) -> bool:
    if asset.kind == "cosyvoice":
        return cosyvoice_complete(locations.cosyvoice_dir)
    if asset.kind == "imagebind":
        return imagebind_complete(locations.imagebind_path)
    if asset.kind == "hf":
        if not asset.repo_id:
            return False
        return hf_snapshot_complete(cache_root_for(asset, locations), asset.repo_id)
    return False


def model_card_url(repo_id: str) -> str:
    return f"https://huggingface.co/{repo_id}"


def format_gated_help(repo_ids: list[str]) -> str:
    unique = list(dict.fromkeys(repo_ids))
    lines = [
        "Accept the Hugging Face terms for the models below (logged-in browser),",
        "then run: make download-models",
        "",
    ]
    lines.extend(f"  {model_card_url(repo_id)}" for repo_id in unique)
    return "\n".join(lines)


def _parse_env_key(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in line:
        return None
    key = line.split("=", 1)[0].strip()
    if key.startswith("export "):
        key = key[7:].strip()
    return key or None


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        key = _parse_env_key(raw_line)
        if key is None:
            continue
        values[key] = raw_line.split("=", 1)[1]
    return values


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


def discover_env_files(root: Path) -> list[Path]:
    root = root.resolve()
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in _SKIP_DIR_NAMES]
        for filename in filenames:
            if filename.startswith(".env.") and not filename.endswith(".example"):
                found.append(Path(dirpath) / filename)
    return sorted(found)


def persist_hf_token(root: Path, token: str) -> list[Path]:
    values = {HF_TOKEN: token, WHISPERX_HF_TOKEN: token}
    written: list[Path] = []
    for path in discover_env_files(root):
        original = path.read_text(encoding="utf-8")
        updated = substitute_env_contents(original, values)
        if updated == original:
            continue
        _write_atomic(path, updated)
        written.append(path)
    return written


def token_from_env_files(root: Path) -> str:
    gpu_env = root / GPU_EXECUTION_ENV
    parsed = parse_env_file(gpu_env)
    return (
        os.environ.get(HF_TOKEN, "").strip()
        or os.environ.get(WHISPERX_HF_TOKEN, "").strip()
        or parsed.get(HF_TOKEN, "").strip()
        or parsed.get(WHISPERX_HF_TOKEN, "").strip()
    )


def prompt_hf_token() -> str:
    return getpass.getpass(
        "Hugging Face token (required for SAM Audio and Whisper diarization): "
    ).strip()


def ensure_host_directories(locations: Locations) -> None:
    locations.hf_home.mkdir(parents=True, exist_ok=True)
    locations.cosyvoice_dir.parent.mkdir(parents=True, exist_ok=True)
    locations.imagebind_path.parent.mkdir(parents=True, exist_ok=True)
    locations.madlad_hf_home.mkdir(parents=True, exist_ok=True)


def print_status(asset: Asset, locations: Locations) -> None:
    if is_complete(asset, locations):
        print(f"skip {asset.title}: already present")
    else:
        print(f"download {asset.title}")


class HuggingfaceDownloader:
    def snapshot(
        self,
        repo_id: str,
        *,
        cache_dir: Path | None = None,
        local_dir: Path | None = None,
        token: str | None = None,
    ) -> None:
        from huggingface_hub import snapshot_download

        try:
            from huggingface_hub.errors import GatedRepoError, LocalEntryNotFoundError
        except ImportError:  # huggingface_hub < 0.23
            from huggingface_hub.utils import GatedRepoError, LocalEntryNotFoundError

        kwargs: dict[str, object] = {"repo_id": repo_id, "token": token or None}
        if local_dir is not None:
            local_dir.mkdir(parents=True, exist_ok=True)
            kwargs["local_dir"] = str(local_dir)
        if cache_dir is not None:
            cache_dir.mkdir(parents=True, exist_ok=True)
            kwargs["cache_dir"] = str(cache_dir)
        try:
            try:
                snapshot_download(**kwargs, local_files_only=True)
                return
            except (LocalEntryNotFoundError, OSError, ValueError):
                snapshot_download(**kwargs, local_files_only=False)
        except GatedRepoError as exc:
            raise GatedDownloadError(repo_id, str(exc)) from exc

    def http_file(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(f".{dest.name}.part")
        try:
            urllib.request.urlretrieve(url, part)
            size = part.stat().st_size
            if size < imagebind_min_bytes():
                raise DownloadModelsError(
                    f"ImageBind download is incomplete ({size} bytes): {url}"
                )
            os.replace(part, dest)
        except DownloadModelsError:
            if part.exists():
                part.unlink()
            raise
        except urllib.error.URLError as exc:
            if part.exists():
                part.unlink()
            raise DownloadModelsError(f"ImageBind download failed: {exc}") from exc
        except Exception:
            if part.exists():
                part.unlink()
            raise


def download_asset(
    asset: Asset,
    locations: Locations,
    *,
    token: str,
    downloader: HubDownloader,
) -> str:
    if is_complete(asset, locations):
        print(f"skip {asset.title}: already present")
        return "skip"
    print(f"downloading {asset.title}")
    if asset.kind == "cosyvoice":
        downloader.snapshot(
            asset.repo_id or cosyvoice_model_id(),
            local_dir=locations.cosyvoice_dir,
            token=token or None,
        )
        if not cosyvoice_complete(locations.cosyvoice_dir):
            raise DownloadModelsError(
                f"CosyVoice model is incomplete: {locations.cosyvoice_dir}"
            )
        return "download"
    if asset.kind == "imagebind":
        downloader.http_file(IMAGEBIND_URL, locations.imagebind_path)
        if not imagebind_complete(locations.imagebind_path):
            raise DownloadModelsError(
                f"ImageBind checkpoint is incomplete: {locations.imagebind_path}"
            )
        return "download"
    if asset.kind == "hf":
        if not asset.repo_id:
            raise DownloadModelsError(f"{asset.title} is missing a repository id")
        downloader.snapshot(
            asset.repo_id,
            cache_dir=cache_root_for(asset, locations),
            token=token or None,
        )
        return "download"
    raise DownloadModelsError(f"Unknown asset kind: {asset.kind}")


def execute_downloads(
    locations: Locations,
    *,
    token: str = "",
    downloader: HubDownloader | None = None,
) -> int:
    active = downloader or HuggingfaceDownloader()
    gated_repos: list[str] = []
    failures: list[str] = []
    for asset in assets():
        try:
            download_asset(asset, locations, token=token, downloader=active)
        except GatedDownloadError as exc:
            print(str(exc), file=sys.stderr)
            gated_repos.append(exc.repo_id)
        except DownloadModelsError as exc:
            print(str(exc), file=sys.stderr)
            failures.append(asset.title)
        except Exception as exc:
            print(
                f"{asset.title} failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            failures.append(asset.title)
    if gated_repos:
        print(file=sys.stderr)
        print(format_gated_help(gated_repos), file=sys.stderr)
    if failures:
        return EXIT_ERROR
    if gated_repos:
        return EXIT_ACTION_REQUIRED
    return EXIT_OK


def compose_download_command(*, token: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--profile",
        "dubbing-init",
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "-e",
        f"{HF_TOKEN}={token}",
        "gpu-dubbing-models-init",
    ]


def run_compose_download(*, root: Path, token: str) -> int:
    env = os.environ.copy()
    env["HOST_UID"] = str(os.getuid())
    env["HOST_GID"] = str(os.getgid())
    if token:
        env[HF_TOKEN] = token
        env[WHISPERX_HF_TOKEN] = token
    command = compose_download_command(token=token)
    try:
        completed = subprocess.run(command, cwd=root, env=env, check=False)
    except FileNotFoundError as exc:
        raise DownloadModelsError(
            "docker is required to download model weights. Install Docker, "
            "then run: make build"
        ) from exc
    if completed.returncode == EXIT_OK:
        return EXIT_OK
    if completed.returncode == EXIT_ACTION_REQUIRED:
        return EXIT_ACTION_REQUIRED
    if completed.returncode != EXIT_ERROR:
        print(
            "Model download failed. If the gpu-execution-worker image is missing, "
            "run: make build",
            file=sys.stderr,
        )
    return EXIT_ERROR


def _gated_pending(locations: Locations) -> list[Asset]:
    return [
        asset
        for asset in assets()
        if asset.gated and not is_complete(asset, locations)
    ]


def _public_pending(locations: Locations) -> list[Asset]:
    return [
        asset
        for asset in assets()
        if not asset.gated and not is_complete(asset, locations)
    ]


def run_host(
    *,
    root: Path,
    interactive: bool,
    compose_runner: Callable[..., int] | None = None,
) -> int:
    locations = host_locations(root)
    listed = assets()
    for asset in listed:
        print_status(asset, locations)
    if all(is_complete(asset, locations) for asset in listed):
        print()
        print("All model weights are already present.")
        return EXIT_OK

    ensure_host_directories(locations)
    token = token_from_env_files(root)
    gated = _gated_pending(locations)
    if gated and not token:
        if interactive:
            token = prompt_hf_token()
            if token:
                persist_hf_token(root, token)
                print("✓ Hugging Face token saved")
        if not token:
            titles = ", ".join(asset.title for asset in gated)
            print(
                f"Hugging Face token is required for: {titles}",
                file=sys.stderr,
            )
            print(format_gated_help([asset.repo_id or "" for asset in gated if asset.repo_id]), file=sys.stderr)
            if not _public_pending(locations):
                return EXIT_ACTION_REQUIRED

    runner = compose_runner or run_compose_download
    try:
        code = runner(root=root, token=token)
    except DownloadModelsError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    if gated and not token and code == EXIT_OK:
        return EXIT_ACTION_REQUIRED
    return code


def main(
    argv: list[str] | None = None,
    *,
    compose_runner: Callable[..., int] | None = None,
    downloader: HubDownloader | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root used for host cache paths and .env files.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Download into the current environment (used inside Compose).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Do not prompt for a Hugging Face token.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.execute:
        token = (
            os.environ.get(HF_TOKEN, "").strip()
            or os.environ.get(WHISPERX_HF_TOKEN, "").strip()
        )
        return execute_downloads(
            execute_locations(),
            token=token,
            downloader=downloader,
        )

    interactive = not args.non_interactive
    if interactive and not sys.stdin.isatty():
        print(
            "download-models requires an interactive terminal, or pass "
            "--non-interactive.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    return run_host(
        root=root,
        interactive=interactive,
        compose_runner=compose_runner,
    )


if __name__ == "__main__":
    raise SystemExit(main())
