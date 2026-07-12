from __future__ import annotations

import httpx

from telegram_agent.core.common.exceptions import (
    TelegramIngressBadResponseError,
    TelegramIngressUnavailableError,
)
from telegram_agent.core.content_processing.common.commands import (
    NotifyAttachmentProcessingResultCommand,
)
from telegram_agent.core.content_processing.common.settings import settings


class TelegramIngressClient:
    def __init__(self) -> None:
        self._base_url = settings.telegram_ingress_base_url.rstrip("/")
        self._token = settings.telegram_ingress_service_token
        self._timeout = httpx.Timeout(settings.telegram_ingress_request_timeout_seconds)

    def notify_processing_result(
        self,
        command: NotifyAttachmentProcessingResultCommand,
    ) -> None:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload = command.model_dump(
            mode="json",
            exclude={"ingress_attachment_id"},
        )
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    (
                        f"{self._base_url}/attachments/"
                        f"{command.ingress_attachment_id}/processing-result"
                    ),
                    headers=headers,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TelegramIngressUnavailableError(
                "Telegram ingress is temporarily unavailable"
            ) from exc

        if response.status_code >= 500 or response.status_code in (408, 429):
            raise TelegramIngressUnavailableError(
                "Telegram ingress is temporarily unavailable"
            )
        if response.status_code >= 400:
            raise TelegramIngressBadResponseError(
                f"Telegram ingress rejected the callback with status {response.status_code}"
            )
