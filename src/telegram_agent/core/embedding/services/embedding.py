from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic

from telegram_agent.core.embedding.common.commands import EmbedChunksCommand, EmbedOptions
from telegram_agent.core.embedding.common.exceptions import InvalidEmbeddingRequestError
from telegram_agent.core.embedding.common.results import (
    EmbedChunksResult,
    EmbeddingItemResult,
)
from telegram_agent.core.embedding.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[EmbedOptions], EmbeddingProvider]


class EmbeddingService:
    def __init__(self, provider_factory: ProviderFactory) -> None:
        self._provider_factory = provider_factory

    async def embed_chunks(self, command: EmbedChunksCommand) -> EmbedChunksResult:
        if not command.chunks:
            raise InvalidEmbeddingRequestError("At least one chunk is required")

        texts: list[str] = []
        for chunk in command.chunks:
            cleaned = chunk.text.strip()
            if not chunk.chunk_id.strip():
                raise InvalidEmbeddingRequestError("chunk_id must be non-empty")
            if not cleaned:
                raise InvalidEmbeddingRequestError(
                    f"Chunk {chunk.chunk_id!r} has empty text"
                )
            texts.append(cleaned)

        provider = self._provider_factory(command.options)
        started_at = monotonic()
        vectors = await provider.embed_texts(
            texts,
            dimensions=command.options.dimensions,
        )
        elapsed_ms = round((monotonic() - started_at) * 1000)

        if not vectors:
            raise InvalidEmbeddingRequestError("Provider returned no embeddings")

        dimensions = len(vectors[0])
        items: list[EmbeddingItemResult] = []
        for index, (chunk, vector) in enumerate(
            zip(command.chunks, vectors, strict=True)
        ):
            vector_tuple = tuple(float(value) for value in vector)
            items.append(
                EmbeddingItemResult(
                    chunk_id=chunk.chunk_id,
                    index=index,
                    embedding=vector_tuple,
                    dimensions=len(vector_tuple),
                )
            )

        model_name = command.options.model or provider.model_name
        logger.info(
            "Completed embedding batch",
            extra={
                "provider": provider.provider_name,
                "model": model_name,
                "count": len(items),
                "dimensions": dimensions,
                "elapsed_ms": elapsed_ms,
            },
        )

        return EmbedChunksResult(
            provider=provider.provider_name,
            model=model_name,
            dimensions=dimensions,
            count=len(items),
            embeddings=tuple(items),
        )
