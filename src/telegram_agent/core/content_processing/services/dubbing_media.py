from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
    StorageError,
)
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.content_processing.db.models.content_processing import (
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitleSegment,
)


@dataclass(frozen=True)
class PlannedDubbingSegment:
    index: int
    source_segment_indices: tuple[int, ...]
    start_ms: int
    end_ms: int
    source_text: str
    target_text: str
    speaker: str | None


class DubbingSegmentPlanner:
    """Build TTS-sized segments without modifying the canonical transcript."""

    def plan(
        self,
        *,
        source_segments: list[TranscriptSegment],
        translated_segments: list[SubtitleSegment],
    ) -> list[PlannedDubbingSegment]:
        source = [item for item in source_segments if (item.text or "").strip()]
        if len(source) != len(translated_segments):
            raise PermanentContentProcessingError(
                "Translated segment count does not match the source transcript"
            )
        planned: list[PlannedDubbingSegment] = []
        for source_item, target_item in zip(source, translated_segments, strict=True):
            candidate = PlannedDubbingSegment(
                index=len(planned),
                source_segment_indices=(source_item.segment_index,),
                start_ms=source_item.start_ms,
                end_ms=source_item.end_ms,
                source_text=" ".join(source_item.text.split()),
                target_text=" ".join(target_item.text.split()),
                speaker=source_item.speaker,
            )
            if planned and self._should_merge(planned[-1], candidate):
                left = planned[-1]
                planned[-1] = PlannedDubbingSegment(
                    index=left.index,
                    source_segment_indices=(
                        left.source_segment_indices + candidate.source_segment_indices
                    ),
                    start_ms=left.start_ms,
                    end_ms=candidate.end_ms,
                    source_text=self._join(left.source_text, candidate.source_text),
                    target_text=self._join(left.target_text, candidate.target_text),
                    speaker=left.speaker or candidate.speaker,
                )
            else:
                planned.append(candidate)
        if not planned:
            raise PermanentContentProcessingError(
                "Cannot build a dubbing plan from an empty transcript"
            )
        return planned

    @staticmethod
    def _should_merge(
        left: PlannedDubbingSegment, right: PlannedDubbingSegment
    ) -> bool:
        if left.speaker and right.speaker and left.speaker != right.speaker:
            return False
        gap = right.start_ms - left.end_ms
        if gap < 250:
            return True
        if gap > 550:
            return False
        return not left.source_text.rstrip().endswith((".", "!", "?", "…"))

    @staticmethod
    def _join(left: str, right: str) -> str:
        if not left:
            return right
        if right[:1] in ".,!?;:%)]}'\"…":
            return f"{left}{right}"
        return f"{left} {right}"


class DubbingAudioAssemblyService:
    """Stream-align and mix TTS clips with the SAM residual using FFmpeg."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._root = Path(settings.media_storage_root).expanduser().resolve()

    def assemble(
        self,
        *,
        job_id: UUID,
        video_path: Path,
        residual_path: Path,
        plan_path: Path,
        tts_manifest_path: Path,
    ) -> Path:
        for path, label in (
            (video_path, "video"),
            (residual_path, "residual audio"),
            (plan_path, "dubbing plan"),
            (tts_manifest_path, "TTS manifest"),
        ):
            self._require_shared_file(path, label)
        duration = self._probe_duration(video_path)
        plan = self._load_json(plan_path)
        tts = self._load_json(tts_manifest_path)
        plan_segments = plan.get("segments")
        tts_segments = tts.get("segments")
        if not isinstance(plan_segments, list) or not isinstance(tts_segments, list):
            raise PermanentContentProcessingError("Invalid dubbing/TTS manifest")
        tts_by_index = {
            int(item["index"]): item
            for item in tts_segments
            if isinstance(item, dict) and "index" in item
        }
        placements: list[tuple[Path, int, int, int]] = []
        for raw in plan_segments:
            if not isinstance(raw, dict):
                raise PermanentContentProcessingError("Invalid dubbing segment")
            try:
                index = int(raw["index"])
                start_ms = int(raw["start_ms"])
                end_ms = int(raw["end_ms"])
                clip = Path(str(tts_by_index[index]["tts_clip_path"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise PermanentContentProcessingError(
                    "TTS manifest is incomplete for audio assembly"
                ) from exc
            self._require_shared_file(clip, f"TTS clip {index}")
            placements.append((clip, start_ms, end_ms, index))
        if not placements:
            raise PermanentContentProcessingError("No TTS clips to assemble")

        job_dir = self._safe_job_dir(job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        speech_canvas = job_dir / "dub_speech_canvas.wav"
        normalized_speech = job_dir / "dub_speech_normalized.wav"
        background = job_dir / "dub_background.wav"
        mixed = job_dir / "dub_mixed_audio.wav"

        self._render_speech_canvas(
            placements=placements,
            duration_seconds=duration,
            output_path=speech_canvas,
            job_dir=job_dir,
        )
        self._loudnorm(speech_canvas, normalized_speech)
        self._standardize_background(
            residual_path, background, duration_seconds=duration
        )
        self._mix(
            speech_path=normalized_speech,
            background_path=background,
            output_path=mixed,
            duration_seconds=duration,
        )
        return mixed

    def _render_speech_canvas(
        self,
        *,
        placements: list[tuple[Path, int, int, int]],
        duration_seconds: float,
        output_path: Path,
        job_dir: Path,
    ) -> None:
        command = [self._settings.ffmpeg_binary, "-y"]
        filters: list[str] = []
        labels: list[str] = []
        fade_seconds = self._settings.dubbing_fade_milliseconds / 1000.0
        for input_index, (path, start_ms, end_ms, _) in enumerate(placements):
            command.extend(("-i", str(path)))
            maximum = max((end_ms - start_ms) / 1000.0, 0.01)
            fade = min(fade_seconds, maximum / 4.0)
            label = f"s{input_index}"
            chain = (
                f"[{input_index}:a]atrim=0:{maximum:.6f},asetpts=PTS-STARTPTS,"
                f"aresample={self._settings.dubbing_sample_rate},"
                f"aformat=channel_layouts={'stereo' if self._settings.dubbing_channels == 2 else 'mono'}"
            )
            if fade > 0:
                chain += (
                    f",afade=t=in:st=0:d={fade:.6f},"
                    f"afade=t=out:st={max(maximum - fade, 0):.6f}:d={fade:.6f}"
                )
            delay = max(start_ms, 0)
            delay_value = f"{delay}|{delay}" if self._settings.dubbing_channels == 2 else str(delay)
            filters.append(f"{chain},adelay={delay_value}[{label}]")
            labels.append(f"[{label}]")
        filters.append(
            "".join(labels)
            + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
            + f"alimiter=limit=0.95,apad=whole_dur={duration_seconds:.6f},"
            + f"atrim=0:{duration_seconds:.6f}[speech]"
        )
        script = job_dir / ".dub_speech_filters.txt"
        script.write_text(";".join(filters), encoding="utf-8")
        temporary = output_path.with_name(f".{output_path.name}.part.wav")
        try:
            command.extend(
                (
                    "-filter_complex_script", str(script), "-map", "[speech]", "-c:a",
                    "pcm_s16le", str(temporary),
                )
            )
            self._run(command, "speech alignment")
            self._adopt(temporary, output_path, "speech canvas")
        finally:
            script.unlink(missing_ok=True)
            temporary.unlink(missing_ok=True)

    def _loudnorm(self, source: Path, output: Path) -> None:
        analysis = self._run(
            [
                self._settings.ffmpeg_binary, "-hide_banner", "-i", str(source),
                "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f",
                "null", "-",
            ],
            "speech loudness analysis",
        )
        match = re.search(r"\{\s*\"input_i\".*?\}", analysis.stderr, re.DOTALL)
        if match is None:
            raise RetryableContentProcessingError(
                "ffmpeg did not return loudness measurements"
            )
        try:
            measured = json.loads(match.group(0))
            loudnorm = (
                "loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
                f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:"
                f"measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}"
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RetryableContentProcessingError(
                "Invalid ffmpeg loudness measurements"
            ) from exc
        temporary = output.with_name(f".{output.name}.part.wav")
        try:
            self._run(
                [
                    self._settings.ffmpeg_binary, "-y", "-i", str(source), "-af",
                    loudnorm, "-c:a", "pcm_s16le", str(temporary),
                ],
                "speech loudness normalization",
            )
            self._adopt(temporary, output, "normalized speech")
        finally:
            temporary.unlink(missing_ok=True)

    def _standardize_background(
        self, source: Path, output: Path, *, duration_seconds: float
    ) -> None:
        layout = "stereo" if self._settings.dubbing_channels == 2 else "mono"
        temporary = output.with_name(f".{output.name}.part.wav")
        try:
            self._run(
                [
                    self._settings.ffmpeg_binary, "-y", "-i", str(source), "-af",
                    f"aresample={self._settings.dubbing_sample_rate},aformat=channel_layouts={layout},"
                    f"apad=whole_dur={duration_seconds:.6f},atrim=0:{duration_seconds:.6f}",
                    "-c:a", "pcm_s16le", str(temporary),
                ],
                "background standardization",
            )
            self._adopt(temporary, output, "standardized background")
        finally:
            temporary.unlink(missing_ok=True)

    def _mix(
        self,
        *,
        speech_path: Path,
        background_path: Path,
        output_path: Path,
        duration_seconds: float,
    ) -> None:
        temporary = output_path.with_name(f".{output_path.name}.part.wav")
        filter_value = (
            f"[0:a]volume={self._settings.dubbing_background_relative_db}dB[bg];"
            "[bg][1:a]sidechaincompress=threshold=0.02:ratio=6:attack=20:release=250[ducked];"
            f"[1:a][ducked]amix=inputs=2:duration=longest:normalize=0,"
            f"alimiter=limit=0.95,atrim=0:{duration_seconds:.6f}[mixed]"
        )
        try:
            self._run(
                [
                    self._settings.ffmpeg_binary, "-y", "-i", str(background_path),
                    "-i", str(speech_path), "-filter_complex", filter_value, "-map",
                    "[mixed]", "-c:a", "pcm_s16le", str(temporary),
                ],
                "dub audio mixing",
            )
            self._adopt(temporary, output_path, "mixed dub audio")
        finally:
            temporary.unlink(missing_ok=True)

    def _probe_duration(self, path: Path) -> float:
        completed = self._run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            "media duration probe",
        )
        try:
            duration = float(completed.stdout.strip())
        except ValueError as exc:
            raise PermanentContentProcessingError(
                "Unable to parse media duration"
            ) from exc
        if duration <= 0:
            raise PermanentContentProcessingError("Media duration must be positive")
        return duration

    def _run(
        self, command: list[str], operation: str
    ) -> subprocess.CompletedProcess[str]:
        if shutil.which(command[0]) is None:
            raise PermanentContentProcessingError(f"Binary is unavailable: {command[0]}")
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._settings.ffmpeg_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RetryableContentProcessingError(f"{operation} timed out") from exc
        except OSError as exc:
            raise RetryableContentProcessingError(f"Unable to run {operation}") from exc
        if completed.returncode:
            detail = (completed.stderr or "")[-1500:]
            raise PermanentContentProcessingError(f"{operation} failed: {detail}")
        return completed

    def _safe_job_dir(self, job_id: UUID) -> Path:
        path = (self._root / str(job_id) / "dubbing").resolve()
        if not path.is_relative_to(self._root):
            raise StorageError("Dubbing directory escaped media storage")
        return path

    @staticmethod
    def _load_json(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PermanentContentProcessingError(
                f"Invalid dubbing manifest: {path.name}"
            ) from exc
        if not isinstance(value, dict):
            raise PermanentContentProcessingError("Dubbing manifest must be an object")
        return value

    @staticmethod
    def _require_file(path: Path, label: str) -> None:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            raise PermanentContentProcessingError(f"Missing or invalid {label}")

    def _require_shared_file(self, path: Path, label: str) -> None:
        resolved = path.expanduser().resolve(strict=False)
        if not resolved.is_relative_to(self._root):
            raise PermanentContentProcessingError(
                f"Dubbing {label} is outside shared media storage"
            )
        self._require_file(resolved, label)

    @staticmethod
    def _adopt(temporary: Path, final: Path, label: str) -> None:
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise RetryableContentProcessingError(f"ffmpeg produced no {label}")
        os.replace(temporary, final)
