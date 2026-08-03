from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    AudioClipError,
    AudioClipPermanentError,
    StorageError,
)
from telegram_agent.core.content_processing.common.settings import Settings


class AudioClipper:
    """Cut a time-bounded audio clip from a source media file via ffmpeg."""

    def __init__(
        self,
        *,
        storage_root: Path,
        ffmpeg_binary: str,
        timeout_seconds: float,
    ) -> None:
        self._storage_root = storage_root.expanduser().resolve()
        self._ffmpeg_binary = ffmpeg_binary
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_settings(cls, settings: Settings) -> "AudioClipper":
        return cls(
            storage_root=Path(settings.media_storage_root),
            ffmpeg_binary=settings.ffmpeg_binary,
            timeout_seconds=settings.ffmpeg_timeout_seconds,
        )

    def clip_path_for_segment(
        self,
        *,
        job_id: UUID,
        segment_index: int,
    ) -> Path:
        return (
            self._storage_root
            / str(job_id)
            / "emotion_clips"
            / f"segment_{segment_index:05d}.ogg"
        )

    def extract_clip(
        self,
        *,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        dest_path: Path,
    ) -> Path:
        if not source_path.is_file() or source_path.is_symlink() or source_path.stat().st_size <= 0:
            raise AudioClipPermanentError("Source media file is missing or invalid")
        if end_ms < start_ms:
            raise AudioClipPermanentError("Invalid clip range: end_ms is before start_ms")
        if end_ms == start_ms:
            raise AudioClipPermanentError("Invalid clip range: zero-duration segment")
        if shutil.which(self._ffmpeg_binary) is None:
            raise AudioClipPermanentError("ffmpeg binary is not available")

        self._create_parent_directory(dest_path)
        temporary_path = dest_path.with_name(f".{dest_path.name}.part")
        start_seconds = start_ms / 1000.0
        duration_seconds = (end_ms - start_ms) / 1000.0
        try:
            self._run_ffmpeg(
                [
                    self._ffmpeg_binary,
                    "-y",
                    "-ss",
                    f"{start_seconds:.3f}",
                    "-i",
                    str(source_path),
                    "-t",
                    f"{duration_seconds:.3f}",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-c:a",
                    "libopus",
                    "-f",
                    "ogg",
                    str(temporary_path),
                ]
            )
            if temporary_path.stat().st_size <= 0:
                raise AudioClipPermanentError("ffmpeg produced an empty audio clip")
            temporary_path.replace(dest_path)
        except AudioClipPermanentError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write audio clip file") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

        return dest_path

    def _create_parent_directory(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("Unable to create clip output directory") from exc

    def _run_ffmpeg(self, command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioClipError("ffmpeg timed out while cutting audio clip") from exc
        except OSError as exc:
            raise AudioClipError("Unable to execute ffmpeg for audio clip") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or b"").decode("utf-8", errors="replace").strip()
            message = stderr or f"ffmpeg exited with code {completed.returncode}"
            if self._is_permanent_ffmpeg_failure(message):
                raise AudioClipPermanentError(message)
            raise AudioClipError(message)

    @staticmethod
    def _is_permanent_ffmpeg_failure(message: str) -> bool:
        lowered = message.lower()
        permanent_markers = (
            "invalid data found",
            "no such file",
            "does not contain any stream",
            "output file does not contain any stream",
            "unknown encoder",
        )
        return any(marker in lowered for marker in permanent_markers)
