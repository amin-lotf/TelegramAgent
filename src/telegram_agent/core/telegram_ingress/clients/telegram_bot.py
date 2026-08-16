"""Thin Bot API client for progressive user notifications."""

from __future__ import annotations

import httpx

from telegram_agent.core.common.exceptions import (
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)


class TelegramBotClient:
    def __init__(
        self,
        *,
        bot_token: str,
        api_base_url: str,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not bot_token:
            raise TelegramDownloadPermanentError("Telegram bot token is not configured")
        self._token = bot_token
        self._base_url = api_base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> int:
        body: dict[str, object] = {"chat_id": chat_id, "text": text[:4096]}
        if reply_to_message_id is not None:
            body["reply_parameters"] = {
                "message_id": reply_to_message_id,
                "allow_sending_without_reply": True,
            }
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}/bot{self._token}/sendMessage",
                    json=body,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramDownloadError(
                "Telegram API is temporarily unavailable while sending a message"
            ) from exc

        if response.status_code >= 500:
            raise TelegramDownloadError(
                f"Telegram sendMessage returned a server error "
                f"(HTTP {response.status_code})"
            )
        if response.status_code >= 400:
            raise TelegramDownloadPermanentError(
                f"Telegram sendMessage was rejected "
                f"(HTTP {response.status_code})"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramDownloadPermanentError(
                "Telegram returned an invalid sendMessage response"
            ) from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise TelegramDownloadPermanentError(
                "Telegram could not accept the notification message"
            )
        result = payload.get("result")
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if not isinstance(message_id, int):
            raise TelegramDownloadPermanentError(
                "Telegram returned an invalid sendMessage result"
            )
        return message_id
