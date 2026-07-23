from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkToEmbed:
    chunk_id: str
    text: str


@dataclass(frozen=True, slots=True)
class EmbedOptions:
    model: str
    dimensions: int | None


@dataclass(frozen=True, slots=True)
class EmbedChunksCommand:
    chunks: tuple[ChunkToEmbed, ...]
    options: EmbedOptions
