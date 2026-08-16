from __future__ import annotations

from uuid import UUID

import httpx

from telegram_agent.core.common.exceptions import (
    TelegramIngressBadResponseError,
    TelegramIngressUnavailableError,
)


class TelegramIngressClient:
    """Synchronous transport adapter for agent-runtime → telegram-ingress calls."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str | None,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    def notify_user(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        text: str,
        group_id: UUID | None = None,
        ingress_message_id: UUID | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        """Send a progressive user-facing text message (status, rejection, error).

        Best-effort from the caller's perspective: failures raise and callers
        should not block processing on success.
        """
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload: dict[str, object] = {
            "chat_id": chat_id,
            "telegram_user_id": telegram_user_id,
            "text": text,
        }
        if group_id is not None:
            payload["group_id"] = str(group_id)
        if ingress_message_id is not None:
            payload["ingress_message_id"] = str(ingress_message_id)
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id

        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}/notifications/messages",
                    headers=headers,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramIngressUnavailableError(
                "Telegram ingress is temporarily unavailable"
            ) from exc
        except httpx.RequestError as exc:
            raise TelegramIngressUnavailableError(
                "Telegram ingress is temporarily unavailable"
            ) from exc

        if response.status_code in {408, 429} or response.status_code >= 500:
            raise TelegramIngressUnavailableError(
                "Telegram ingress is temporarily unavailable"
            )
        if response.status_code >= 400:
            raise TelegramIngressBadResponseError(
                f"Telegram ingress rejected notify with status {response.status_code}"
            )

    # Back-compat alias used by older tests/call sites.
    def notify_request_preparing(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        text: str,
        group_id: UUID | None = None,
        ingress_message_id: UUID | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.notify_user(
            chat_id=chat_id,
            telegram_user_id=telegram_user_id,
            text=text,
            group_id=group_id,
            ingress_message_id=ingress_message_id,
            reply_to_message_id=reply_to_message_id,
        )
