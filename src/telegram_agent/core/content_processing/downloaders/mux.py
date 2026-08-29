from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    MediaDemuxError,
    MediaDemuxPermanentError,
    SecondaryTaskCancelledError,
    StorageError,
)
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.content_processing.downloaders.cancellable_process import (
    CancellableProcessRunner,
)

# ASS FontSize is relative to PlayResY. Soft ASS in MKV scales correctly, so
# use a normal caption size (~4% of frame height) — not the tiny values we
# tried when fighting broken MP4 mov_text rendering.
_MIN_ASS_FONT_SIZE = 28
_MAX_ASS_FONT_SIZE = 52


class MuxService:
    """Combine video, audio, and soft subtitles into a Matroska (MKV) file.

    MKV supports real soft subtitle tracks (SRT/ASS) with proper styling.
    We convert the prepared SRT into a styled ASS track (PlayRes + FontSize)
    and mux with stream copy for video (no slow burn-in re-encode).

    The ``audio_path`` argument is an intentional extension point: a future
    dubbing stage can supply a translated/synthesized track without changing
    the mux API. This service always re-muxes; it never copies the original
    source container as the result.
    """

    def __init__(
        self,
        *,
        storage_root: Path,
        ffmpeg_binary: str,
        timeout_seconds: float,
        cancel_grace_seconds: float = 5.0,
    ) -> None:
        self._storage_root = storage_root.expanduser().resolve()
        self._ffmpeg_binary = ffmpeg_binary
        self._timeout_seconds = timeout_seconds
        self._process_runner = CancellableProcessRunner(
            cancel_grace_seconds=cancel_grace_seconds
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "MuxService":
        return cls(
            storage_root=Path(settings.media_storage_root),
            ffmpeg_binary=settings.ffmpeg_binary,
            timeout_seconds=settings.ffmpeg_timeout_seconds,
            cancel_grace_seconds=settings.ffmpeg_cancel_grace_seconds,
        )

    def mux(
        self,
        *,
        job_id: UUID,
        video_path: str,
        audio_path: str,
        subtitle_path: str,
        subtitle_language: str | None = None,
        subtitle_title: str | None = None,
        audio_language: str | None = None,
        audio_bitrate: str | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> str:
        video = Path(video_path)
        audio = Path(audio_path)
        subtitle = Path(subtitle_path)

        for path, label in (
            (video, "video"),
            (audio, "audio"),
            (subtitle, "subtitle"),
        ):
            if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
                raise MediaDemuxPermanentError(
                    f"Mux input {label} file is missing or invalid"
                )

        if shutil.which(self._ffmpeg_binary) is None:
            raise MediaDemuxPermanentError("ffmpeg binary is not available")

        width, height = self._probe_video_size(
            video, cancellation_requested=cancellation_requested
        )
        output_path = self._output_path(job_id)
        self._create_parent_directory(output_path)
        temporary_path = output_path.with_name(
            f".{output_path.stem}.part{output_path.suffix}"
        )
        ass_path = output_path.with_name(f".{output_path.stem}.ass")
        subtitle_language_tag = self._language_tag(subtitle_language, default="eng")
        audio_language_tag = self._language_tag(audio_language, default="und")
        safe_subtitle_title = self._metadata_title(
            subtitle_title or subtitle_language,
            default="English",
        )

        try:
            self._write_styled_ass(
                srt_path=subtitle,
                ass_path=ass_path,
                width=width,
                height=height,
            )
            # Soft ASS in MKV: video stream copy, audio re-encode for container safety,
            # styled subtitles as a proper soft track (not burn-in).
            self._run_ffmpeg(
                [
                    self._ffmpeg_binary,
                    "-y",
                    "-i",
                    str(video),
                    "-i",
                    str(audio),
                    "-i",
                    str(ass_path),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-map",
                    "2:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    audio_bitrate or "128k",
                    "-metadata:s:a:0",
                    f"language={audio_language_tag}",
                    "-c:s",
                    "ass",
                    "-metadata:s:s:0",
                    f"language={subtitle_language_tag}",
                    "-metadata:s:s:0",
                    f"title={safe_subtitle_title}",
                    "-disposition:s:0",
                    "default",
                    "-f",
                    "matroska",
                    str(temporary_path),
                ],
                cancellation_requested=cancellation_requested,
            )
            if cancellation_requested is not None and cancellation_requested():
                raise SecondaryTaskCancelledError("Secondary task was cancelled")
            if temporary_path.stat().st_size <= 0:
                raise MediaDemuxPermanentError("ffmpeg produced an empty muxed file")
            temporary_path.replace(output_path)
        except (MediaDemuxPermanentError, MediaDemuxError):
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write muxed media file") from exc
        finally:
            temporary_path.unlink(missing_ok=True)
            ass_path.unlink(missing_ok=True)

        return str(output_path)

    @staticmethod
    def _language_tag(value: str | None, *, default: str) -> str:
        if value is None:
            return default
        normalized = re.sub(r"[^a-z0-9-]", "", value.strip().lower())[:32]
        return normalized or default

    @staticmethod
    def _metadata_title(value: str | None, *, default: str) -> str:
        if value is None:
            return default
        normalized = " ".join(value.split())[:128]
        return normalized or default

    def _write_styled_ass(
        self,
        *,
        srt_path: Path,
        ass_path: Path,
        width: int,
        height: int,
    ) -> None:
        """Convert SRT → ASS with PlayRes and a compact FontSize for soft playback."""
        # ~4% of height (e.g. ~43 on 1080p) — typical soft-sub caption scale.
        font_size = max(_MIN_ASS_FONT_SIZE, min(_MAX_ASS_FONT_SIZE, height // 25))
        events = self._srt_to_ass_events(srt_path.read_text(encoding="utf-8"))
        # PrimaryColour/OutlineColour are ASS &HAABBGGRR
        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "WrapStyle: 0\n"
            "ScaledBorderAndShadow: yes\n"
            f"PlayResX: {width}\n"
            f"PlayResY: {height}\n"
            "YCbCr Matrix: TV.709\n"
            "\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            f"Style: Default,Arial,{font_size},"
            "&H00FFFFFF,&H000000FF,&H00000000,&H64000000,"
            "0,0,0,0,100,100,0,0,1,1.6,0.8,2,60,60,40,1\n"
            "\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
            "Effect, Text\n"
        )
        ass_path.write_text(header + events, encoding="utf-8")

    def _srt_to_ass_events(self, srt_text: str) -> str:
        blocks = [b.strip() for b in srt_text.replace("\r\n", "\n").split("\n\n") if b.strip()]
        lines: list[str] = []
        for block in blocks:
            parts = block.split("\n")
            if len(parts) < 3:
                continue
            # index line may be omitted in some SRTs; find the arrow line
            timing_idx = next(
                (i for i, line in enumerate(parts) if "-->" in line),
                None,
            )
            if timing_idx is None:
                continue
            timing = parts[timing_idx]
            try:
                start_raw, end_raw = [p.strip() for p in timing.split("-->")]
                start = self._srt_time_to_ass(start_raw)
                end = self._srt_time_to_ass(end_raw)
            except (ValueError, IndexError):
                continue
            text = "\\N".join(parts[timing_idx + 1 :])
            text = text.replace("{", "\\{").replace("}", "\\}")
            if not text.strip():
                continue
            lines.append(
                f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n"
            )
        if not lines:
            raise PermanentSubtitleError(
                "Subtitle file has no usable cues for ASS conversion"
            )
        return "".join(lines)

    @staticmethod
    def _srt_time_to_ass(value: str) -> str:
        # SRT: HH:MM:SS,mmm  →  ASS: H:MM:SS.cs (centiseconds)
        value = value.strip().replace(",", ".")
        hh, mm, rest = value.split(":")
        ss, frac = rest.split(".")
        # ASS uses centiseconds (2 digits)
        cs = int(round(int(frac.ljust(3, "0")[:3]) / 10))
        if cs >= 100:
            cs = 99
        return f"{int(hh)}:{int(mm):02d}:{int(ss):02d}.{cs:02d}"

    def _probe_video_size(
        self,
        video: Path,
        *,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> tuple[int, int]:
        try:
            completed = self._process_runner.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=width,height",
                    "-of",
                    "json",
                    str(video),
                ],
                timeout_seconds=min(self._timeout_seconds, 30.0),
                cancellation_requested=cancellation_requested,
            )
        except FileNotFoundError as exc:
            raise MediaDemuxPermanentError("ffprobe binary is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaDemuxError("ffprobe timed out while reading video size") from exc
        except OSError as exc:
            raise MediaDemuxError("Unable to start ffprobe") from exc

        if completed.returncode != 0:
            raise MediaDemuxPermanentError("Unable to probe source video dimensions")

        try:
            payload = json.loads(completed.stdout or "{}")
            stream = (payload.get("streams") or [{}])[0]
            width = int(stream["width"])
            height = int(stream["height"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MediaDemuxPermanentError(
                "Source video has no usable width/height"
            ) from exc

        if width <= 0 or height <= 0:
            raise MediaDemuxPermanentError("Source video has invalid dimensions")
        return width, height

    def _output_path(self, job_id: UUID) -> Path:
        # Short, unique basename shown to the user in Telegram.
        short_id = job_id.hex[:10]
        path = (self._storage_root / str(job_id) / f"v{short_id}.mkv").resolve()
        try:
            path.relative_to(self._storage_root)
        except ValueError as exc:
            raise StorageError("Resolved mux path is outside storage root") from exc
        return path

    def _create_parent_directory(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("Unable to create mux storage directory") from exc

    def _run_ffmpeg(
        self,
        command: list[str],
        *,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> None:
        try:
            completed = self._process_runner.run(
                command,
                timeout_seconds=self._timeout_seconds,
                cancellation_requested=cancellation_requested,
            )
        except FileNotFoundError as exc:
            raise MediaDemuxPermanentError("ffmpeg binary is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaDemuxError("ffmpeg timed out while muxing media") from exc
        except OSError as exc:
            raise MediaDemuxError("Unable to start ffmpeg") from exc

        if completed.returncode == 0:
            return

        stderr_raw = completed.stderr or ""
        stderr = stderr_raw.lower()
        if any(
            marker in stderr
            for marker in (
                "does not contain any stream",
                "output file does not contain any stream",
                "stream map",
                "matches no streams",
                "invalid data",
                "error opening input",
                "unable to choose an output format",
            )
        ):
            raise MediaDemuxPermanentError("Media is invalid for mux")
        detail = stderr_raw.strip().splitlines()[-1] if stderr_raw.strip() else ""
        message = f"ffmpeg mux failed with exit code {completed.returncode}"
        if detail:
            message = f"{message}: {detail}"
        raise MediaDemuxError(message)


class PermanentSubtitleError(MediaDemuxPermanentError):
    """Raised when subtitle cues cannot be converted for muxing."""
