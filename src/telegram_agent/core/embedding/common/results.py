from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmbeddingItemResult:
    chunk_id: str
    index: int
    embedding: tuple[float, ...]
    dimensions: int


@dataclass(frozen=True, slots=True)
class EmbedChunksResult:
    provider: str
    model: str
    dimensions: int
    count: int
    embeddings: tuple[EmbeddingItemResult, ...]
