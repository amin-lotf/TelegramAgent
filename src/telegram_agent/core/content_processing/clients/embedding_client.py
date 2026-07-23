from __future__ import annotations

import httpx
from pydantic import ValidationError

from telegram_agent.core.common.exceptions import (
    EmbeddingResponseError,
    EmbeddingServiceError,
)
from telegram_agent.core.content_processing.common.results import (
    EmbeddingChunkInput,
    EmbeddingItemResult,
    EmbeddingResult,
)
from telegram_agent.core.content_processing.common.settings import Settings
from telegram_agent.core.embedding.api.v1.embeddings.schemas import EmbedChunksResponse


class EmbeddingClient:
    def __init__(self, settings: Settings) -> None:
        self._url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
        self._timeout = httpx.Timeout(settings.embedding_request_timeout_seconds)
        self._token = settings.embedding_service_token

    def embed_chunks(
        self,
        *,
        chunks: tuple[EmbeddingChunkInput, ...],
        model: str | None = None,
        dimensions: int | None = None,
    ) -> EmbeddingResult:
        headers: dict[str, str] = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        payload: dict[str, object] = {
            "chunks": [
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                }
                for chunk in chunks
            ],
        }
        options: dict[str, object] = {}
        if model is not None:
            options["model"] = model
        if dimensions is not None:
            options["dimensions"] = dimensions
        if options:
            payload["options"] = options

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(self._url, headers=headers, json=payload)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise EmbeddingServiceError(
                "Embedding service is temporarily unavailable"
            ) from exc

        if response.status_code >= 500 or response.status_code in (408, 429):
            raise EmbeddingServiceError("Embedding service is temporarily unavailable")
        if response.status_code >= 400:
            raise EmbeddingResponseError("Embedding service rejected the request")

        try:
            response_data = EmbedChunksResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise EmbeddingResponseError(
                "Embedding service returned an invalid response"
            ) from exc

        if response_data.count != len(response_data.embeddings):
            raise EmbeddingResponseError(
                "Embedding service returned inconsistent embedding count"
            )

        items: list[EmbeddingItemResult] = []
        for item in response_data.embeddings:
            if item.dimensions != len(item.embedding):
                raise EmbeddingResponseError(
                    "Embedding service returned inconsistent vector dimensions"
                )
            items.append(
                EmbeddingItemResult(
                    chunk_id=item.chunk_id,
                    index=item.index,
                    embedding=tuple(item.embedding),
                    dimensions=item.dimensions,
                )
            )

        return EmbeddingResult(
            provider=response_data.provider,
            model=response_data.model,
            dimensions=response_data.dimensions,
            count=response_data.count,
            embeddings=tuple(items),
        )
