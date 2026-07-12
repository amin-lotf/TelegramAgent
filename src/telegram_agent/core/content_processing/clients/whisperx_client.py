from __future__ import annotations

from pathlib import Path

import httpx
from pydantic import ValidationError

from telegram_agent.core.common.exceptions import WhisperXResponseError, WhisperXServiceError
from telegram_agent.core.common.utils import seconds_to_ms
from telegram_agent.core.content_processing.common.results import (
    TranscriptionResult,
    TranscriptionSegmentResult,
)
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.whisperx.api.v1.transcriptions.schemas import WhisperXTranscriptResponse


class WhisperXClient:
    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.whisperx_base_url.rstrip('/')}/audio/transcriptions"
        self._model = settings.whisperx_model
        self._timeout = httpx.Timeout(settings.whisperx_request_timeout_seconds)
        self._token = settings.whisperx_service_token

    def transcribe(
        self,
        *,
        path: Path,
        mime_type: str | None,
        request_id: str,
    ) -> TranscriptionResult:
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise WhisperXResponseError("Downloaded media file is missing or invalid")
        headers = {"X-Request-Id": request_id}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with path.open("rb") as media_file, httpx.Client(timeout=self._timeout) as client:
                response = client.post(
                    self._url,
                    headers=headers,
                    data={"model": self._model, "response_format": "verbose_json", "temperature": "0"},
                    files={"file": (path.name, media_file, mime_type or "application/octet-stream")},
                )
        except (OSError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise WhisperXServiceError("WhisperX service is temporarily unavailable") from exc
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise WhisperXServiceError("WhisperX service is temporarily unavailable")
        if response.status_code >= 400:
            raise WhisperXResponseError("WhisperX rejected the transcription request")
        try:
            response_data = WhisperXTranscriptResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise WhisperXResponseError("WhisperX returned an invalid transcription response") from exc
        segments: list[TranscriptionSegmentResult] = []
        for segment in response_data.segments:
            start_ms = seconds_to_ms(segment.start)
            end_ms = seconds_to_ms(segment.end)
            if start_ms is None or end_ms is None or end_ms < start_ms:
                raise WhisperXResponseError("WhisperX returned an invalid transcript segment")
            segments.append(
                TranscriptionSegmentResult(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=segment.text,
                    language=segment.language,
                    language_probability=segment.language_probability,
                    speaker=segment.speaker,
                    speaker_confidence=segment.speaker_confidence,
                )
            )
        return TranscriptionResult(
            text=response_data.text,
            language=response_data.language,
            language_probability=response_data.language_probability,
            duration_ms=seconds_to_ms(response_data.duration),
            segments=tuple(segments),
        )
