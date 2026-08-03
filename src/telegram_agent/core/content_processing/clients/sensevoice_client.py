from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import ValidationError

from telegram_agent.core.common.exceptions import (
    SenseVoiceResponseError,
    SenseVoiceServiceError,
)
from telegram_agent.core.content_processing.common.results import SegmentEmotionResult
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.sensevoice.api.v1.emotions.schemas import (
    SenseVoiceEmotionResponse,
)


class SenseVoiceClient:
    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.sensevoice_base_url.rstrip('/')}/audio/emotions"
        self._model = settings.sensevoice_model
        self._timeout = httpx.Timeout(settings.sensevoice_request_timeout_seconds)
        self._token = settings.sensevoice_service_token

    def extract_emotion(
        self,
        *,
        path: Path,
        mime_type: str | None,
        request_id: str,
        language: str | None = None,
    ) -> SegmentEmotionResult:
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise SenseVoiceResponseError("Audio clip file is missing or invalid")
        headers = {"X-Request-Id": request_id}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        data: dict[str, str] = {"model": self._model}
        if language:
            data["language"] = language
        try:
            with path.open("rb") as media_file, httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    self._url,
                    headers=headers,
                    data=data,
                    files={
                        "file": (
                            path.name,
                            media_file,
                            mime_type or "application/octet-stream",
                        )
                    },
                )
        except (OSError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise SenseVoiceServiceError(
                f"SenseVoice service is temporarily unavailable ({type(exc).__name__}: {exc})"
            ) from exc
        if response.status_code >= 500 or response.status_code in (408, 429):
            detail = (response.text or "").strip()
            if len(detail) > 300:
                detail = detail[:300] + "..."
            raise SenseVoiceServiceError(
                "SenseVoice service is temporarily unavailable "
                f"(HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
                + ")"
            )
        if response.status_code >= 400:
            detail = (response.text or "").strip()
            if len(detail) > 300:
                detail = detail[:300] + "..."
            raise SenseVoiceResponseError(
                "SenseVoice rejected the emotion extraction request "
                f"(HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
                + ")"
            )
        try:
            response_data = SenseVoiceEmotionResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise SenseVoiceResponseError(
                "SenseVoice returned an invalid emotion extraction response"
            ) from exc
        return SegmentEmotionResult(
            emotion=response_data.emotion,
            events=tuple(response_data.events),
            language=response_data.language,
            text=response_data.text,
        )
