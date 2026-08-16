from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)


logger = logging.getLogger(__name__)


class _OutputTooShort(RuntimeError):
    pass


class CosyVoiceDubbingBatchWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        payload = _load_object(input_path)
        segments = payload.get("segments")
        if not isinstance(segments, list) or not segments:
            raise GpuWorkloadPermanentError(
                "CosyVoice dubbing manifest must contain non-empty segments"
            )

        model_id = str(parameters.get("model") or "").strip()
        installed_model = os.getenv(
            "COSYVOICE_MODEL_ID", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
        )
        if model_id and model_id != installed_model:
            raise GpuWorkloadPermanentError(
                f"CosyVoice model {model_id!r} is not installed in this worker"
            )
        model_dir = Path(
            os.getenv(
                "COSYVOICE_MODEL_DIR",
                "/opt/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B",
            )
        )
        if not model_dir.is_dir():
            raise GpuWorkloadPermanentError(
                f"CosyVoice model directory is missing: {model_dir}"
            )

        output_dir = _shared_path(payload.get("output_dir"), must_exist=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = output_dir / "tts_manifest.json"
        mode = str(parameters.get("inference_mode") or "cross_lingual")
        if mode not in ("cross_lingual", "zero_shot"):
            raise GpuWorkloadPermanentError(
                f"Unsupported CosyVoice inference mode: {mode}"
            )

        try:
            from cosyvoice.cli.cosyvoice import AutoModel

            logger.info("Loading CosyVoice model model=%s", installed_model)
            model = AutoModel(model_dir=str(model_dir))
        except Exception as exc:
            raise GpuWorkloadRetryableError(
                f"Unable to load CosyVoice model: {type(exc).__name__}: {exc}"
            ) from exc

        completed = _load_completed_manifest(manifest_path)
        results: list[dict[str, object]] = []
        try:
            for raw in segments:
                segment = _segment_object(raw)
                index = int(segment["index"])
                logger.info(
                    "Synthesizing CosyVoice segment index=%s total=%s",
                    index,
                    len(segments),
                )
                clip_path = output_dir / f"segment_{index:05d}.wav"
                cached = completed.get(index)
                if cached is not None and _valid_wav(clip_path):
                    results.append(cached)
                    continue

                prompt_path = _shared_path(segment.get("prompt_path"), must_exist=True)
                target_text = str(segment.get("target_text") or "").strip()
                source_text = str(segment.get("source_text") or "").strip()
                if not target_text:
                    raise GpuWorkloadPermanentError(
                        f"Dubbing segment {index} has empty target text"
                    )
                target_seconds = max(
                    (
                        int(str(segment["end_ms"]))
                        - int(str(segment["start_ms"]))
                    )
                    / 1000.0,
                    0.05,
                )
                synthesis = self._synthesize_segment(
                    model=model,
                    mode=mode,
                    prompt_path=prompt_path,
                    source_text=source_text,
                    target_text=target_text,
                    target_seconds=target_seconds,
                    output_path=clip_path,
                    parameters=parameters,
                )
                entry: dict[str, object] = {
                    "index": index,
                    "start_ms": int(str(segment["start_ms"])),
                    "end_ms": int(str(segment["end_ms"])),
                    "speaker": segment.get("speaker"),
                    "source_text": source_text,
                    "target_text": target_text,
                    "tts_clip_path": str(clip_path),
                    **synthesis,
                }
                results.append(entry)
                _write_json_atomic(
                    manifest_path,
                    {
                        "model": installed_model,
                        "inference_mode": mode,
                        "segments": sorted(
                            results, key=lambda item: int(str(item["index"]))
                        ),
                    },
                )
        finally:
            del model
            try:
                import torch

                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    if hasattr(torch.cuda, "ipc_collect"):
                        torch.cuda.ipc_collect()
            except Exception:
                pass

        _write_json_atomic(
            output_path,
            {
                "model": installed_model,
                "manifest_path": str(manifest_path),
                "segment_count": len(results),
            },
        )
        logger.info("CosyVoice batch complete segment_count=%s", len(results))

    def _synthesize_segment(
        self,
        *,
        model: Any,
        mode: str,
        prompt_path: Path,
        source_text: str,
        target_text: str,
        target_seconds: float,
        output_path: Path,
        parameters: dict[str, object],
    ) -> dict[str, object]:
        prefix = str(
            parameters.get("prompt_prefix")
            or "You are a helpful assistant.<|endofprompt|>"
        )
        max_speed = float(str(parameters.get("duration_fit_max_speed") or 1.3))
        target_ratio = float(
            str(parameters.get("duration_fit_target_ratio") or 0.98)
        )
        short_speed = float(str(parameters.get("short_text_speed") or 0.5))
        max_attempts = int(str(parameters.get("short_text_max_attempts") or 5))
        initial_speed = short_speed if len(target_text.split()) <= 2 else 1.0
        desired = max(target_seconds * target_ratio, 0.05)

        with tempfile.TemporaryDirectory(prefix="cosyvoice-segment-") as directory:
            temporary_dir = Path(directory)
            normalized_prompt = temporary_dir / "prompt.wav"
            _run_ffmpeg(
                [
                    "ffmpeg", "-y", "-i", str(prompt_path), "-vn", "-ac", "1",
                    "-ar", "24000", "-c:a", "pcm_s16le", str(normalized_prompt),
                ]
            )
            best_path: Path | None = None
            best_duration = float("inf")
            used_speed = initial_speed
            last_short: Exception | None = None
            for attempt in range(max_attempts):
                speed = min(max_speed, initial_speed * (1.12 ** attempt))
                candidate = temporary_dir / f"candidate-{attempt}.wav"
                try:
                    pcm, sample_rate = _collect_model_audio(
                        _invoke_model(
                            model=model,
                            mode=mode,
                            target_text=f"{prefix}{target_text}",
                            prompt_text=f"{prefix}{source_text}",
                            prompt_path=normalized_prompt,
                            speed=speed,
                        ),
                        sample_rate=int(getattr(model, "sample_rate", 24_000)),
                    )
                    _write_pcm_wav(candidate, pcm=pcm, sample_rate=sample_rate)
                except _OutputTooShort as exc:
                    last_short = exc
                    continue
                duration = _wav_duration(candidate)
                if duration < best_duration:
                    best_duration = duration
                    best_path = candidate
                    used_speed = speed
                if duration <= desired:
                    break

            source = "cosyvoice"
            if best_path is None:
                if _normalized_text(source_text) == _normalized_text(target_text):
                    best_path = normalized_prompt
                    best_duration = _wav_duration(best_path)
                    source = "prompt_audio_fallback"
                else:
                    raise GpuWorkloadPermanentError(
                        f"CosyVoice produced no usable speech: {last_short or 'empty output'}"
                    )

            silence_trimmed = temporary_dir / "trimmed.wav"
            _run_ffmpeg(
                [
                    "ffmpeg", "-y", "-i", str(best_path), "-af",
                    "silenceremove=stop_periods=-1:stop_duration=0.30:stop_threshold=-50dB:stop_silence=0.12:detection=rms",
                    str(silence_trimmed),
                ],
                allow_empty_fallback=True,
            )
            fitted_source = silence_trimmed if _valid_wav(silence_trimmed) else best_path
            fitted_duration = _wav_duration(fitted_source)
            tempo: float | None = None
            if fitted_duration > desired:
                tempo = fitted_duration / desired
                fitted = temporary_dir / "fitted.wav"
                _run_ffmpeg(
                    [
                        "ffmpeg", "-y", "-i", str(fitted_source), "-af",
                        f"rubberband=tempo={tempo:.8f}", str(fitted),
                    ]
                )
                fitted_source = fitted
                fitted_duration = _wav_duration(fitted_source)

            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_output = output_path.with_name(f".{output_path.name}.part")
            shutil.copyfile(fitted_source, temporary_output)
            if not _valid_wav(temporary_output):
                temporary_output.unlink(missing_ok=True)
                raise GpuWorkloadRetryableError("CosyVoice produced an invalid WAV file")
            os.replace(temporary_output, output_path)
            return {
                "source": source,
                "synthesis_speed": used_speed,
                "rubberband_tempo": tempo,
                "duration_seconds": fitted_duration,
                "target_duration_seconds": target_seconds,
            }


def _invoke_model(
    *, model: Any, mode: str, target_text: str, prompt_text: str,
    prompt_path: Path, speed: float,
) -> Iterator[dict[str, Any]]:
    if mode == "zero_shot":
        return model.inference_zero_shot(
            target_text, prompt_text, str(prompt_path), speed=speed
        )
    return model.inference_cross_lingual(target_text, str(prompt_path), speed=speed)


def _collect_model_audio(
    chunks: Iterator[dict[str, Any]], *, sample_rate: int
) -> tuple[bytes, int]:
    values: list[bytes] = []
    try:
        for chunk in chunks:
            speech = chunk.get("tts_speech") if isinstance(chunk, dict) else None
            if speech is None:
                continue
            waveform = speech.detach().cpu().numpy()
            values.append(
                (np.clip(waveform, -1.0, 1.0) * (2**15 - 1))
                .astype(np.int16)
                .tobytes()
            )
    except RuntimeError as exc:
        if "Kernel size can't be greater" in str(exc):
            raise _OutputTooShort(str(exc)) from exc
        raise
    pcm = b"".join(values)
    if len(pcm) < int(sample_rate * 0.2) * 2:
        raise _OutputTooShort("CosyVoice output was shorter than 200 ms")
    return pcm, sample_rate


def _write_pcm_wav(path: Path, *, pcm: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm)


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except (OSError, wave.Error, ZeroDivisionError) as exc:
        raise GpuWorkloadPermanentError(f"Invalid WAV file: {path}") from exc


def _valid_wav(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.stat().st_size > 44 and _wav_duration(path) > 0
    except (OSError, GpuWorkloadPermanentError):
        return False


def _load_completed_manifest(path: Path) -> dict[int, dict[str, object]]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        segments = payload.get("segments", []) if isinstance(payload, dict) else []
        return {
            int(item["index"]): item
            for item in segments
            if isinstance(item, dict) and "index" in item
        }
    except (OSError, ValueError, TypeError):
        return {}


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GpuWorkloadPermanentError("CosyVoice input manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise GpuWorkloadPermanentError("CosyVoice input manifest must be an object")
    return payload


def _segment_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GpuWorkloadPermanentError("Invalid CosyVoice segment entry")
    try:
        int(value["index"])
        int(value["start_ms"])
        int(value["end_ms"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GpuWorkloadPermanentError("Invalid CosyVoice segment timing") from exc
    return value


def _shared_path(value: object, *, must_exist: bool) -> Path:
    path = Path(str(value or "")).expanduser().resolve(strict=False)
    root = Path(os.getenv("GPU_SHARED_STORAGE_ROOT", "/app/media")).resolve()
    if not path.is_relative_to(root):
        raise GpuWorkloadPermanentError("CosyVoice path is outside shared storage")
    if must_exist and (path.is_symlink() or not path.is_file() or path.stat().st_size <= 0):
        raise GpuWorkloadPermanentError(f"CosyVoice input is missing or invalid: {path}")
    return path


def _run_ffmpeg(command: list[str], *, allow_empty_fallback: bool = False) -> None:
    try:
        completed = subprocess.run(command, capture_output=True, timeout=600, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GpuWorkloadRetryableError("Unable to execute ffmpeg for CosyVoice") from exc
    if completed.returncode != 0 and not allow_empty_fallback:
        detail = completed.stderr.decode("utf-8", errors="replace")[-1000:]
        raise GpuWorkloadPermanentError(f"CosyVoice audio conversion failed: {detail}")


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split()).strip(".!?…")


def create_handler() -> GpuWorkloadHandler:
    return CosyVoiceDubbingBatchWorkload()
