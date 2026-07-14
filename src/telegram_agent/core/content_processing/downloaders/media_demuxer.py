from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    MediaDemuxError,
    MediaDemuxPermanentError,
    StorageError,
)
from telegram_agent.core.content_processing.common.results import MediaDemuxResult
from telegram_agent.core.content_processing.common.settings import Settings


class MediaDemuxer:
    """Extract audio and video tracks from a downloaded media container via ffmpeg."""

    def __init__(
        self,
        *,
        storage_root: Path,
        ffmpeg_binary: str,
        timeout_seconds: float,
        max_bytes: int,
    ) -> None:
        self._storage_root = storage_root.expanduser().resolve()
        self._ffmpeg_binary = ffmpeg_binary
        self._timeout_seconds = timeout_seconds
        self._max_bytes = max_bytes

    @classmethod
    def from_settings(cls, settings: Settings) -> "MediaDemuxer":
        return cls(
            storage_root=Path(settings.media_storage_root),
            ffmpeg_binary=settings.ffmpeg_binary,
            timeout_seconds=settings.ffmpeg_timeout_seconds,
            max_bytes=settings.media_download_max_bytes,
        )

    def demux(
        self,
        *,
        job_id: UUID,
        source_asset_id: UUID,
        source_path: str,
    ) -> MediaDemuxResult:
        source = Path(source_path)
        if not source.is_file() or source.is_symlink() or source.stat().st_size <= 0:
            raise MediaDemuxPermanentError("Source media file is missing or invalid")

        if shutil.which(self._ffmpeg_binary) is None:
            raise MediaDemuxPermanentError("ffmpeg binary is not available")

        audio_path = self._derived_path(job_id, source_asset_id, "audio", ".ogg")
        video_path = self._derived_path(
            job_id,
            source_asset_id,
            "video",
            source.suffix if source.suffix else ".mp4",
        )

        if not self._valid_existing_file(audio_path):
            self._extract_audio(source=source, audio_path=audio_path)
        if not self._valid_existing_file(video_path):
            self._extract_video(source=source, video_path=video_path)

        if not self._valid_existing_file(audio_path):
            raise MediaDemuxPermanentError("Demux produced no usable audio track")
        if not self._valid_existing_file(video_path):
            raise MediaDemuxPermanentError("Demux produced no usable video track")

        return MediaDemuxResult(
            audio_path=str(audio_path),
            audio_size_bytes=audio_path.stat().st_size,
            audio_mime_type="audio/ogg",
            video_path=str(video_path),
            video_size_bytes=video_path.stat().st_size,
            video_mime_type=self._guess_video_mime(video_path),
        )

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(
            f".{path.stem}.part{path.suffix}"
        )

    def _extract_audio(self, *, source: Path, audio_path: Path) -> None:
        self._create_parent_directory(audio_path)
        temporary_path = audio_path.with_name(f".{audio_path.name}.part")
        try:
            # Prefer re-encoding to ogg/opus so WhisperX always receives a stable audio file.
            self._run_ffmpeg(
                [
                    self._ffmpeg_binary,
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
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
                raise MediaDemuxPermanentError("ffmpeg produced an empty audio file")
            temporary_path.replace(audio_path)
        except MediaDemuxPermanentError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write demuxed audio file") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def _extract_video(self, *, source: Path, video_path: Path) -> None:
        self._create_parent_directory(video_path)
        temporary_path = self._temporary_path(video_path)
        try:
            self._run_ffmpeg(
                [
                    self._ffmpeg_binary,
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-an",
                    "-sn",
                    "-dn",
                    "-c:v",
                    "copy",
                    str(temporary_path),
                ]
            )
            if temporary_path.stat().st_size <= 0:
                raise MediaDemuxPermanentError("ffmpeg produced an empty video file")
            temporary_path.replace(video_path)
        except MediaDemuxPermanentError:
            temporary_path.unlink(missing_ok=True)
            raise
        except OSError as exc:
            temporary_path.unlink(missing_ok=True)
            raise StorageError("Unable to write demuxed video file") from exc
        finally:
            temporary_path.unlink(missing_ok=True)

    def _run_ffmpeg(self, command: list[str]) -> None:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MediaDemuxPermanentError("ffmpeg binary is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise MediaDemuxError("ffmpeg timed out while demuxing media") from exc
        except OSError as exc:
            raise MediaDemuxError("Unable to start ffmpeg") from exc

        if completed.returncode == 0:
            return

        stderr = (completed.stderr or "").lower()
        if any(
            marker in stderr
            for marker in (
                "does not contain any stream",
                "output file does not contain any stream",
                "stream map",
                "no audio",
                "matches no streams",
            )
        ):
            raise MediaDemuxPermanentError("Media has no usable audio or video stream")
        if "invalid data" in stderr or "error opening input" in stderr:
            raise MediaDemuxPermanentError("Media file is invalid for demux")
        raise MediaDemuxError(
            f"ffmpeg demux failed with exit code {completed.returncode}"
        )

    def _derived_path(
        self,
        job_id: UUID,
        source_asset_id: UUID,
        role: str,
        suffix: str,
    ) -> Path:
        safe_suffix = suffix if suffix.startswith(".") else f".{suffix}"
        path = (
            self._storage_root / str(job_id) / f"{source_asset_id}.{role}{safe_suffix}"
        ).resolve()
        try:
            path.relative_to(self._storage_root)
        except ValueError as exc:
            raise StorageError("Resolved demux path is outside storage root") from exc
        return path

    def _create_parent_directory(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StorageError("Unable to create media storage directory") from exc

    def _valid_existing_file(self, path: Path) -> bool:
        try:
            return (
                path.is_file()
                and not path.is_symlink()
                and 0 < path.stat().st_size <= self._max_bytes
            )
        except OSError:
            return False

    @staticmethod
    def _guess_video_mime(path: Path) -> str | None:
        suffix = path.suffix.lower()
        return {
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
            ".mov": "video/quicktime",
        }.get(suffix)
