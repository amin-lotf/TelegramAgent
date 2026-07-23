from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TranscriptSegmentInput:
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None = None
    speaker_confidence: float | None = None


@dataclass(frozen=True, slots=True)
class ChunkingOptions:
    target_chunk_duration_ms: int
    max_chunk_chars: int
    max_chunk_tokens: int
    overlap_duration_ms: int
    overlap_segments: int


@dataclass(frozen=True, slots=True)
class ChunkTranscriptCommand:
    language: str | None
    duration_ms: int | None
    segments: tuple[TranscriptSegmentInput, ...]
    options: ChunkingOptions
