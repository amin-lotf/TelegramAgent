from __future__ import annotations

import httpx
from pydantic import ValidationError

from telegram_agent.core.chunking.api.v1.chunking.schemas import ChunkTranscriptResponse
from telegram_agent.core.common.exceptions import ChunkingResponseError, ChunkingServiceError
from telegram_agent.core.content_processing.common.results import (
    ChunkingResult,
    ChunkingSegmentInput,
    ChunkResultItem,
)
from telegram_agent.core.content_processing.common.settings import Settings


class ChunkingClient:
    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.chunking_base_url.rstrip('/')}/chunking/transcripts"
        self._timeout = httpx.Timeout(settings.chunking_request_timeout_seconds)
        self._token = settings.chunking_service_token

    def chunk_transcript(
        self,
        *,
        language: str | None,
        duration_ms: int | None,
        segments: tuple[ChunkingSegmentInput, ...],
    ) -> ChunkingResult:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload = {
            "language": language,
            "duration_ms": duration_ms,
            "segments": [
                {
                    "segment_index": segment.segment_index,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": segment.text,
                    "speaker": segment.speaker,
                    "speaker_confidence": segment.speaker_confidence,
                }
                for segment in segments
            ],
        }

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(self._url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ChunkingServiceError("Chunking service is temporarily unavailable") from exc

        if response.status_code >= 500 or response.status_code in (408, 429):
            raise ChunkingServiceError("Chunking service is temporarily unavailable")
        if response.status_code >= 400:
            raise ChunkingResponseError("Chunking service rejected the request")

        try:
            response_data = ChunkTranscriptResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise ChunkingResponseError("Chunking service returned an invalid response") from exc

        chunks: list[ChunkResultItem] = []
        for chunk in response_data.chunks:
            if chunk.end_ms < chunk.start_ms:
                raise ChunkingResponseError("Chunking service returned an invalid chunk")
            chunks.append(
                ChunkResultItem(
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    segment_index_start=chunk.segment_index_start,
                    segment_index_end=chunk.segment_index_end,
                    speakers=tuple(chunk.speakers),
                )
            )

        return ChunkingResult(
            content_type=response_data.content_type,
            strategy=response_data.strategy,
            chunk_count=response_data.chunk_count,
            chunks=tuple(chunks),
        )
