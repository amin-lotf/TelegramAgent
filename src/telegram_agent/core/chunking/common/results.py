from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChunkResult:
    chunk_index: int
    text: str
    start_ms: int
    end_ms: int
    char_count: int
    token_count: int
    segment_index_start: int
    segment_index_end: int
    speakers: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TranscriptChunkingResult:
    content_type: str
    strategy: str
    chunk_count: int
    chunks: tuple[ChunkResult, ...]
