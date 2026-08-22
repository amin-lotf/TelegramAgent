from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)


logger = logging.getLogger(__name__)

_DEFAULT_SAM_AUDIO_CHECKPOINTS_DIR = "/app/.checkpoints"


class SamAudioResidualWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        payload = _load_object(input_path)
        source_path = _shared_file(payload.get("source_audio_path"))
        residual_path = _shared_output(payload.get("residual_path"))
        description = str(parameters.get("description") or "human speech").strip()
        chunk_seconds = float(str(parameters.get("chunk_seconds") or 10.0))
        overlap_seconds = float(str(parameters.get("overlap_seconds") or 2.5))
        if not description:
            raise GpuWorkloadPermanentError("SAM Audio description must not be empty")
        if chunk_seconds <= 0 or overlap_seconds <= 0 or overlap_seconds >= chunk_seconds:
            raise GpuWorkloadPermanentError("Invalid SAM Audio chunk/overlap settings")

        if _valid_audio(residual_path):
            _write_json_atomic(
                output_path,
                {
                    "model": str(parameters.get("model") or ""),
                    "residual_path": str(residual_path),
                    "duration_seconds": _probe_duration(residual_path),
                    "reused": True,
                },
            )
            return

        model_name = str(parameters.get("model") or "facebook/sam-audio-small")
        installed_model = os.getenv("SAM_AUDIO_MODEL", "facebook/sam-audio-small")
        if model_name != installed_model:
            raise GpuWorkloadPermanentError(
                f"SAM Audio model {model_name!r} is not installed in this worker"
            )
        hf_token = os.getenv("HF_TOKEN", "").strip()
        if not hf_token:
            raise GpuWorkloadPermanentError(
                "HF_TOKEN is required for the gated SAM Audio model"
            )

        try:
            import torch
            from huggingface_hub import login
            from sam_audio import SAMAudio, SAMAudioProcessor

            if not torch.cuda.is_available():
                raise GpuWorkloadPermanentError("CUDA is unavailable for SAM Audio")
            login(token=hf_token, add_to_git_credential=False)
            dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
            checkpoint_dir = _prepare_imagebind_checkpoint_dir()
            logger.info(
                "Loading SAM Audio model model=%s imagebind_checkpoints=%s",
                model_name,
                checkpoint_dir,
            )
            model = SAMAudio.from_pretrained(model_name).to(
                device="cuda", dtype=dtype
            ).eval()
            processor = SAMAudioProcessor.from_pretrained(model_name)
            sample_rate = int(
                getattr(processor, "audio_sampling_rate", 48_000) or 48_000
            )
        except GpuWorkloadPermanentError:
            raise
        except Exception as exc:
            raise GpuWorkloadRetryableError(
                f"Unable to load SAM Audio model: {type(exc).__name__}: {exc}"
            ) from exc

        total_seconds = _probe_duration(source_path)
        windows = _chunk_windows(
            total_seconds=total_seconds,
            chunk_seconds=chunk_seconds,
            overlap_seconds=overlap_seconds,
        )
        residual_chunks: list[np.ndarray] = []
        try:
            with tempfile.TemporaryDirectory(prefix="sam-audio-") as directory:
                work_dir = Path(directory)
                for index, (start, end) in enumerate(windows):
                    logger.info(
                        "Separating SAM Audio chunk index=%s total=%s start=%.3f end=%.3f",
                        index,
                        len(windows),
                        start,
                        end,
                    )
                    chunk_path = work_dir / f"chunk-{index:05d}.wav"
                    _extract_chunk(
                        source_path,
                        chunk_path,
                        start_seconds=start,
                        duration_seconds=end - start,
                        sample_rate=sample_rate,
                    )
                    batch: Any = None
                    separation: Any = None
                    try:
                        batch = processor(
                            audios=[str(chunk_path)], descriptions=[description]
                        ).to("cuda")
                        if getattr(batch, "audios", None) is not None:
                            batch.audios = batch.audios.to(dtype=dtype)
                        with torch.inference_mode(), torch.autocast(
                            device_type="cuda", dtype=dtype
                        ):
                            separation = model.separate(
                                batch,
                                predict_spans=False,
                                reranking_candidates=1,
                            )
                        raw_residual = separation.residual
                        if isinstance(raw_residual, (list, tuple)):
                            if not raw_residual:
                                raise GpuWorkloadRetryableError(
                                    "SAM Audio returned no residual waveform"
                                )
                            raw_residual = raw_residual[0]
                        residual = np.asarray(
                            raw_residual.detach().float().cpu().numpy(),
                            dtype=np.float32,
                        ).reshape(-1)
                        expected = int(round((end - start) * sample_rate))
                        residual_chunks.append(_match_length(residual, expected))
                    finally:
                        del separation
                        del batch
                        torch.cuda.empty_cache()

            stitched = _crossfade(
                residual_chunks,
                overlap_samples=int(round(overlap_seconds * sample_rate)),
            )
            expected_total = int(round(total_seconds * sample_rate))
            stitched = _match_length(stitched, expected_total)
            residual_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = residual_path.with_name(f".{residual_path.name}.part")
            sf.write(str(temporary), stitched, sample_rate, format="WAV", subtype="PCM_16")
            if not _valid_audio(temporary):
                raise GpuWorkloadRetryableError("SAM Audio produced invalid residual audio")
            os.replace(temporary, residual_path)
        finally:
            del model
            del processor
            try:
                torch.cuda.empty_cache()
                if hasattr(torch.cuda, "ipc_collect"):
                    torch.cuda.ipc_collect()
            except Exception:
                pass

        _write_json_atomic(
            output_path,
            {
                "model": model_name,
                "residual_path": str(residual_path),
                "duration_seconds": total_seconds,
                "sample_rate": sample_rate,
                "chunk_count": len(windows),
            },
        )
        logger.info("SAM Audio separation complete chunk_count=%s", len(windows))


def _chunk_windows(
    *, total_seconds: float, chunk_seconds: float, overlap_seconds: float
) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    cursor = 0.0
    hop = chunk_seconds - overlap_seconds
    while cursor < total_seconds:
        end = min(total_seconds, cursor + chunk_seconds)
        windows.append((cursor, end))
        if end >= total_seconds:
            break
        cursor += hop
    if not windows:
        raise GpuWorkloadPermanentError("Source audio is empty")
    return windows


def _crossfade(chunks: list[np.ndarray], *, overlap_samples: int) -> np.ndarray:
    if not chunks:
        raise GpuWorkloadPermanentError("SAM Audio produced no residual chunks")
    result = chunks[0].astype(np.float32, copy=True)
    for chunk in chunks[1:]:
        overlap = min(overlap_samples, result.size, chunk.size)
        if overlap:
            fade_in = np.linspace(0.0, 1.0, overlap, dtype=np.float32)
            result[-overlap:] = result[-overlap:] * (1.0 - fade_in) + chunk[:overlap] * fade_in
        result = np.concatenate((result, chunk[overlap:]))
    return result


def _match_length(value: np.ndarray, expected: int) -> np.ndarray:
    if value.size > expected:
        return value[:expected]
    if value.size < expected:
        return np.pad(value, (0, expected - value.size))
    return value


def _prepare_imagebind_checkpoint_dir() -> Path:
    """Point ImageBind at a persistent CWD/.checkpoints directory.

    ``imagebind_huge(pretrained=True)`` writes ``imagebind_huge.pth`` relative
    to the process CWD, not ``HF_HOME``. Without this, each SAM run can
    re-download ~4.5 GiB.
    """
    raw = os.getenv(
        "SAM_AUDIO_CHECKPOINTS_DIR", _DEFAULT_SAM_AUDIO_CHECKPOINTS_DIR
    ).strip()
    checkpoint_dir = Path(raw or _DEFAULT_SAM_AUDIO_CHECKPOINTS_DIR).expanduser()
    try:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise GpuWorkloadPermanentError(
            f"Unable to create SAM ImageBind checkpoint directory: {checkpoint_dir}"
        ) from exc
    os.chdir(checkpoint_dir.parent)
    return checkpoint_dir.resolve()


def _extract_chunk(
    source: Path,
    output: Path,
    *,
    start_seconds: float,
    duration_seconds: float,
    sample_rate: int,
) -> None:
    _run(
        [
            "ffmpeg", "-y", "-ss", f"{start_seconds:.6f}", "-i", str(source),
            "-t", f"{duration_seconds:.6f}", "-vn", "-ac", "1", "-ar",
            str(sample_rate), "-c:a", "pcm_s16le", str(output),
        ],
        "SAM Audio chunk extraction",
    )


def _probe_duration(path: Path) -> float:
    completed = _run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        "SAM Audio duration probe",
    )
    try:
        value = float(completed.stdout.decode("utf-8").strip())
    except ValueError as exc:
        raise GpuWorkloadPermanentError("Unable to parse source audio duration") from exc
    if value <= 0:
        raise GpuWorkloadPermanentError("Source audio duration must be positive")
    return value


def _run(command: list[str], operation: str) -> subprocess.CompletedProcess[bytes]:
    try:
        completed = subprocess.run(
            command, capture_output=True, timeout=600, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GpuWorkloadRetryableError(f"{operation} could not run") from exc
    if completed.returncode:
        detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
        raise GpuWorkloadPermanentError(f"{operation} failed: {detail}")
    return completed


def _valid_audio(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size > 44
    except OSError:
        return False


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GpuWorkloadPermanentError("SAM Audio input manifest is invalid") from exc
    if not isinstance(value, dict):
        raise GpuWorkloadPermanentError("SAM Audio input manifest must be an object")
    return value


def _shared_file(value: object) -> Path:
    path = _shared_output(value)
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise GpuWorkloadPermanentError(f"SAM Audio source is missing: {path}")
    return path


def _shared_output(value: object) -> Path:
    path = Path(str(value or "")).expanduser().resolve(strict=False)
    root = Path(os.getenv("GPU_SHARED_STORAGE_ROOT", "/app/media")).resolve()
    if not path.is_relative_to(root):
        raise GpuWorkloadPermanentError("SAM Audio path is outside shared storage")
    return path


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def create_handler() -> GpuWorkloadHandler:
    return SamAudioResidualWorkload()
