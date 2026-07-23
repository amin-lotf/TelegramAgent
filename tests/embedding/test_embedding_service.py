from __future__ import annotations

from collections.abc import Sequence

import pytest

from telegram_agent.core.embedding.common.commands import (
    ChunkToEmbed,
    EmbedChunksCommand,
    EmbedOptions,
)
from telegram_agent.core.embedding.common.exceptions import InvalidEmbeddingRequestError
from telegram_agent.core.embedding.services.embedding import EmbeddingService


class StubProvider:
    provider_name = "stub"
    model_name = "stub-model"

    def __init__(self, vectors: Sequence[Sequence[float]] | None = None) -> None:
        self.vectors = vectors
        self.calls: list[tuple[tuple[str, ...], int | None]] = []

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        dimensions: int | None = None,
    ) -> Sequence[Sequence[float]]:
        self.calls.append((tuple(texts), dimensions))
        if self.vectors is not None:
            return self.vectors
        return [[float(index), float(index + 1)] for index, _ in enumerate(texts)]


def _command(
    *items: tuple[str, str],
    model: str = "stub-model",
    dimensions: int | None = None,
) -> EmbedChunksCommand:
    return EmbedChunksCommand(
        chunks=tuple(ChunkToEmbed(chunk_id=chunk_id, text=text) for chunk_id, text in items),
        options=EmbedOptions(model=model, dimensions=dimensions),
    )


@pytest.mark.asyncio
async def test_embed_chunks_preserves_order_and_ids() -> None:
    provider = StubProvider()
    service = EmbeddingService(provider_factory=lambda _options: provider)

    result = await service.embed_chunks(
        _command(
            ("id-a", " first text "),
            ("id-b", "second text"),
        )
    )

    assert result.provider == "stub"
    assert result.model == "stub-model"
    assert result.count == 2
    assert result.dimensions == 2
    assert result.embeddings[0].chunk_id == "id-a"
    assert result.embeddings[0].index == 0
    assert result.embeddings[0].embedding == (0.0, 1.0)
    assert result.embeddings[1].chunk_id == "id-b"
    assert result.embeddings[1].index == 1
    assert result.embeddings[1].embedding == (1.0, 2.0)
    assert provider.calls[0][0] == ("first text", "second text")


@pytest.mark.asyncio
async def test_empty_batch_is_rejected() -> None:
    provider = StubProvider()
    service = EmbeddingService(provider_factory=lambda _options: provider)

    with pytest.raises(InvalidEmbeddingRequestError, match="At least one chunk"):
        await service.embed_chunks(
            EmbedChunksCommand(
                chunks=(),
                options=EmbedOptions(model="stub-model", dimensions=None),
            )
        )


@pytest.mark.asyncio
async def test_whitespace_only_text_is_rejected() -> None:
    provider = StubProvider()
    service = EmbeddingService(provider_factory=lambda _options: provider)

    with pytest.raises(InvalidEmbeddingRequestError, match="empty text"):
        await service.embed_chunks(_command(("id-a", "   ")))


@pytest.mark.asyncio
async def test_empty_chunk_id_is_rejected() -> None:
    provider = StubProvider()
    service = EmbeddingService(provider_factory=lambda _options: provider)

    with pytest.raises(InvalidEmbeddingRequestError, match="chunk_id"):
        await service.embed_chunks(_command(("  ", "hello")))
