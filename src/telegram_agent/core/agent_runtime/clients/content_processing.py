from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from telegram_agent.core.common.exceptions import (
    ContentProcessingBadResponseError,
    ContentProcessingUnavailableError,
)


class ContentProcessingClient:
    """Synchronous transport adapter for agent-runtime → content-processing calls."""

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

    def submit_video_download(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        group_id: UUID,
        agent_message_id: UUID,
        media_ingress_message_id: UUID,
        assistant_text: str,
        requested_subtitle_language: str | None,
        requested_dub_language: str | None,
        idempotency_key: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        self._post_download(
            path="/downloads/video",
            payload={
                "chat_id": chat_id,
                "telegram_user_id": telegram_user_id,
                "group_id": str(group_id),
                "agent_message_id": str(agent_message_id),
                "media_ingress_message_id": str(media_ingress_message_id),
                "assistant_text": assistant_text,
                "reply_to_message_id": reply_to_message_id,
                "requested_subtitle_language": requested_subtitle_language,
                "requested_dub_language": requested_dub_language,
            },
            idempotency_key=idempotency_key,
        )

    def submit_audio_download(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        group_id: UUID,
        agent_message_id: UUID,
        media_ingress_message_id: UUID,
        assistant_text: str,
        requested_language: str | None,
        idempotency_key: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        self._post_download(
            path="/downloads/audio",
            payload={
                "chat_id": chat_id,
                "telegram_user_id": telegram_user_id,
                "group_id": str(group_id),
                "agent_message_id": str(agent_message_id),
                "media_ingress_message_id": str(media_ingress_message_id),
                "assistant_text": assistant_text,
                "reply_to_message_id": reply_to_message_id,
                "requested_language": requested_language,
            },
            idempotency_key=idempotency_key,
        )

    def submit_document_download(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        group_id: UUID,
        agent_message_id: UUID,
        media_ingress_message_id: UUID,
        assistant_text: str,
        requested_format: str | None,
        idempotency_key: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        self._post_download(
            path="/downloads/documents",
            payload={
                "chat_id": chat_id,
                "telegram_user_id": telegram_user_id,
                "group_id": str(group_id),
                "agent_message_id": str(agent_message_id),
                "media_ingress_message_id": str(media_ingress_message_id),
                "assistant_text": assistant_text,
                "reply_to_message_id": reply_to_message_id,
                "requested_format": requested_format,
            },
            idempotency_key=idempotency_key,
        )

    def _post_download(
        self,
        *,
        path: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> None:
        headers: dict[str, str] = {
            "Idempotency-Key": idempotency_key,
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ContentProcessingUnavailableError(
                "Content processing service is unavailable"
            ) from exc
        except httpx.RequestError as exc:
            raise ContentProcessingUnavailableError(
                "Content processing service is unavailable"
            ) from exc

        if response.status_code in {408, 429} or response.status_code >= 500:
            raise ContentProcessingUnavailableError(
                "Content processing service is unavailable"
            )
        if response.status_code >= 400:
            raise ContentProcessingBadResponseError(
                "Content processing rejected the download request "
                f"with status {response.status_code}"
            )
