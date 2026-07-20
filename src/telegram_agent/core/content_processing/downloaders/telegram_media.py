from __future__ import annotations

import errno
import os
from pathlib import Path
from uuid import UUID, uuid4

from telegram_agent.core.common.exceptions import (
    StorageError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.content_processing.clients.telegram_client import TelegramClient

from telegram_agent.core.content_processing.common.results import (
    MediaDownloadResult,
    TelegramDownloadContext, TelegramFileStream,
)
from telegram_agent.core.content_processing.common.settings import Settings


class TelegramMediaDownloader:
    def __init__(
        self,
        *,
        telegram_client: TelegramClient,
        storage_root: Path,
        max_bytes: int,
        chunk_size: int,
    ) -> None:
        self._telegram_client = telegram_client
        self._storage_root = storage_root.expanduser().resolve()
        self._max_bytes = max_bytes
        self._chunk_size = chunk_size

    @classmethod
    def from_settings(cls, settings: Settings) -> "TelegramMediaDownloader":
        return cls(
            telegram_client=TelegramClient(settings),
            storage_root=Path(settings.media_storage_root),
            max_bytes=settings.media_download_max_bytes,
            chunk_size=settings.media_download_chunk_size,
        )

    def download(self, context: TelegramDownloadContext) -> MediaDownloadResult:
        telegram_file = self._telegram_client.get_file(context.telegram_file_id)
        if telegram_file.size_bytes is not None and telegram_file.size_bytes > self._max_bytes:
            raise TelegramDownloadPermanentError("Telegram file exceeds configured download size")

        final_path = self._final_path(
            context.job_id,
            context.media_asset_id,
            telegram_file.path,
            media_type=context.media_type,
        )
        if self._valid_existing_file(final_path):
            return MediaDownloadResult(str(final_path), final_path.stat().st_size, None)
        return self._store_stream(file_path=telegram_file.path, final_path=final_path)

    def _store_stream(self, *, file_path: str, final_path: Path) -> MediaDownloadResult:
        self._create_parent_directory(final_path)
        temporary_path = final_path.with_name(
            f".{final_path.name}.{uuid4().hex}.part"
        )
        bytes_written = 0
        try:
            with self._telegram_client.stream_file(
                file_path=file_path,
                chunk_size=self._chunk_size,
            ) as stream:
                self._validate_content_length(stream)
                with temporary_path.open("xb") as output:
                    for chunk in stream.chunks:
                        bytes_written += len(chunk)
                        if bytes_written > self._max_bytes:
                            raise TelegramDownloadPermanentError("Telegram file exceeds configured download size")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            if bytes_written <= 0:
                raise TelegramDownloadPermanentError("Telegram returned an empty file")
            os.replace(temporary_path, final_path)
            return MediaDownloadResult(str(final_path), bytes_written, stream.mime_type)
        except OSError as exc:
            self._raise_storage_error(exc, "Unable to write downloaded media")
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _create_parent_directory(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._raise_storage_error(exc, "Unable to create media storage directory")

    def _final_path(
        self,
        job_id: UUID,
        asset_id: UUID,
        remote_path: str,
        *,
        media_type: str,
    ) -> Path:
        suffix = self._resolve_suffix(remote_path, media_type=media_type)
        path = (self._storage_root / str(job_id) / f"{asset_id}{suffix}").resolve()
        try:
            path.relative_to(self._storage_root)
        except ValueError as exc:
            raise StorageError("Resolved media path is outside storage root") from exc
        return path

    @staticmethod
    def _resolve_suffix(remote_path: str, *, media_type: str) -> str:
        """Pick a container extension ffmpeg and downstream tools can handle.

        Local Bot API (--local) often returns absolute paths without an extension
        (e.g. .../videos/file_1). Saving those as .bin makes video remux fail.
        """
        suffix = Path(remote_path).suffix.lower()
        if suffix and len(suffix) <= 16 and suffix.replace(".", "").isalnum():
            # Treat opaque placeholders as missing so we can map from media type.
            if suffix not in {".bin", ".dat", ".tmp", ".part"}:
                return suffix

        media = media_type.lower()
        if media in {"video", "video_note"}:
            return ".mp4"
        if media == "voice":
            return ".ogg"
        if media == "audio":
            return ".mp3"
        if media == "photo":
            return ".jpg"
        if media == "animation":
            return ".mp4"
        return ".bin"

    def _validate_content_length(self, stream: TelegramFileStream) -> None:
        if stream.content_length is not None and stream.content_length > self._max_bytes:
            raise TelegramDownloadPermanentError("Telegram file exceeds configured download size")

    def _raise_storage_error(self, error: OSError, message: str) -> None:
        if error.errno in (errno.EACCES, errno.EPERM):
            raise TelegramDownloadPermanentError("Media storage is not writable") from error
        raise StorageError(message) from error

    def _valid_existing_file(self, path: Path) -> bool:
        try:
            return path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= self._max_bytes
        except OSError:
            return False
