from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx

from telegram_agent.core.common.exceptions import (
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.content_processing.common.results import (
    TelegramDeliveryResult,
    TelegramFile,
    TelegramFileStream,
)
from telegram_agent.core.content_processing.common.settings import Settings


class TelegramClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.telegram_bot_token:
            raise TelegramDownloadPermanentError("Telegram bot token is not configured")
        self._token = settings.telegram_bot_token
        self._base_url = settings.telegram_api_base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=settings.media_http_connect_timeout_seconds,
            read=settings.media_http_read_timeout_seconds,
            write=settings.media_http_write_timeout_seconds,
            pool=settings.media_http_pool_timeout_seconds,
        )

    def send_video(
        self,
        *,
        chat_id: int,
        file_path: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        return self._send_media(
            method="sendVideo",
            field_name="video",
            chat_id=chat_id,
            file_path=file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )

    def send_audio(
        self,
        *,
        chat_id: int,
        file_path: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        return self._send_media(
            method="sendAudio",
            field_name="audio",
            chat_id=chat_id,
            file_path=file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )

    def send_document(
        self,
        *,
        chat_id: int,
        file_path: str,
        caption: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        return self._send_media(
            method="sendDocument",
            field_name="document",
            chat_id=chat_id,
            file_path=file_path,
            caption=caption,
            reply_to_message_id=reply_to_message_id,
        )

    def _send_media(
        self,
        *,
        method: str,
        field_name: str,
        chat_id: int,
        file_path: str,
        caption: str | None,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        path = Path(file_path)
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise TelegramDownloadPermanentError(
                "Prepared download file is missing or invalid"
            )

        # Multipart form fields must be strings; nested reply_parameters is JSON.
        data: dict[str, str] = {"chat_id": str(chat_id)}
        if caption:
            data["caption"] = caption[:1024]
        if reply_to_message_id is not None:
            data["reply_parameters"] = self._reply_parameters_json(reply_to_message_id)

        try:
            with path.open("rb") as handle:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.post(
                        f"{self._base_url}/bot{self._token}/{method}",
                        data=data,
                        files={field_name: (path.name, handle)},
                    )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDownloadError(
                "Telegram API is temporarily unavailable while sending media"
            ) from exc
        except OSError as exc:
            raise TelegramDownloadPermanentError(
                "Unable to read prepared download file"
            ) from exc

        self._raise_for_telegram_status(response, operation=method)
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramDownloadPermanentError(
                f"Telegram returned an invalid {method} response"
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            description = payload.get("description") if isinstance(payload, dict) else None
            detail = f": {description}" if isinstance(description, str) and description else ""
            raise TelegramDownloadPermanentError(
                f"Telegram could not accept the {method} upload{detail}"
            )
        return self._delivery_result(payload, operation=method)

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        body: dict[str, object] = {"chat_id": chat_id, "text": text[:4096]}
        if reply_to_message_id is not None:
            body["reply_parameters"] = self._reply_parameters(reply_to_message_id)
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/bot{self._token}/sendMessage",
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDownloadError(
                "Telegram API is temporarily unavailable while sending a message"
            ) from exc
        self._raise_for_telegram_status(response, operation="sendMessage")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramDownloadPermanentError(
                "Telegram returned an invalid sendMessage response"
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise TelegramDownloadPermanentError(
                "Telegram could not accept the delivery status message"
            )
        return self._delivery_result(payload, operation="sendMessage")

    @staticmethod
    def _reply_parameters(message_id: int) -> dict[str, object]:
        return {
            "message_id": message_id,
            "allow_sending_without_reply": True,
        }

    @classmethod
    def _reply_parameters_json(cls, message_id: int) -> str:
        return json.dumps(cls._reply_parameters(message_id), separators=(",", ":"))

    @staticmethod
    def _delivery_result(
        payload: dict[str, object], *, operation: str
    ) -> TelegramDeliveryResult:
        result = payload.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            raise TelegramDownloadPermanentError(
                f"Telegram returned an invalid {operation} result"
            )
        return TelegramDeliveryResult(message_id=message_id)

    def get_file(self, file_id: str) -> TelegramFile:
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    f"{self._base_url}/bot{self._token}/getFile",
                    json={"file_id": file_id},
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDownloadError("Telegram API is temporarily unavailable") from exc
        self._raise_for_telegram_status(response, operation="getFile")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramDownloadPermanentError("Telegram returned an invalid getFile response") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            description = payload.get("description") if isinstance(payload, dict) else None
            detail = f": {description}" if isinstance(description, str) and description else ""
            raise TelegramDownloadPermanentError(
                f"Telegram could not resolve the requested file{detail}"
            )
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TelegramDownloadPermanentError("Telegram returned an invalid getFile result")
        path = result.get("file_path")
        if not isinstance(path, str) or not path.strip():
            raise TelegramDownloadPermanentError("Telegram getFile response has no file path")
        size = result.get("file_size")
        return TelegramFile(path=path, size_bytes=size if isinstance(size, int) else None)

    @contextmanager
    def stream_file(
        self,
        *,
        file_path: str,
        chunk_size: int,
    ) -> Iterator[TelegramFileStream]:
        # Local Bot API (--local) returns absolute paths from getFile. Those files
        # are already on disk; the HTTP /file/bot... endpoint returns 404 for them.
        # Read directly when the path is absolute and present.
        local_path = Path(file_path)
        if local_path.is_absolute():
            yield from self._stream_local_file(local_path, chunk_size=chunk_size)
            return

        try:
            with httpx.Client(timeout=self._timeout) as client:
                with client.stream("GET", self._file_url(file_path)) as response:
                    self._raise_for_telegram_status(response, operation="file download")
                    yield TelegramFileStream(
                        mime_type=self._mime_type(response.headers.get("content-type")),
                        content_length=self._content_length(response.headers.get("content-length")),
                        chunks=response.iter_bytes(chunk_size),
                    )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDownloadError("Telegram file download was interrupted") from exc

    def _stream_local_file(
        self,
        local_path: Path,
        *,
        chunk_size: int,
    ) -> Iterator[TelegramFileStream]:
        try:
            if not local_path.is_file() or local_path.is_symlink():
                raise TelegramDownloadPermanentError(
                    "Local Bot API file path is missing or not a regular file. "
                    "Ensure the telegram-bot-api data volume is mounted into this service."
                )
            size = local_path.stat().st_size
            if size <= 0:
                raise TelegramDownloadPermanentError("Local Bot API file is empty")

            def chunks() -> Iterator[bytes]:
                with local_path.open("rb") as handle:
                    while True:
                        data = handle.read(chunk_size)
                        if not data:
                            break
                        yield data

            yield TelegramFileStream(
                mime_type=None,
                content_length=size,
                chunks=chunks(),
            )
        except OSError as exc:
            raise TelegramDownloadError(
                "Unable to read file from local Bot API storage"
            ) from exc

    @staticmethod
    def _mime_type(value: str | None) -> str | None:
        return value.split(";", 1)[0].strip() or None if value else None

    @staticmethod
    def _content_length(value: str | None) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def _raise_for_telegram_status(self, response: httpx.Response, *, operation: str) -> None:
        if response.status_code < 400:
            return
        body_preview = ""
        try:
            text = response.text
            if text:
                body_preview = f" ({text[:300]})"
        except Exception:
            body_preview = ""
        if response.status_code >= 500:
            raise TelegramDownloadError(
                f"Telegram {operation} returned a server error "
                f"(HTTP {response.status_code}){body_preview}"
            )
        raise TelegramDownloadPermanentError(
            f"Telegram {operation} was rejected "
            f"(HTTP {response.status_code}){body_preview}"
        )

    def _file_url(self, file_path: str) -> str:
        # This token-bearing URL is never logged or persisted.
        return f"{self._base_url}/file/bot{self._token}/{file_path.lstrip('/')}"
