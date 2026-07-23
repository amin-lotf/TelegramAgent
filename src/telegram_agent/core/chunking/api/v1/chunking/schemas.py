from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TranscriptSegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segment_index: int = Field(..., ge=0)
    start_ms: int = Field(..., ge=0)
    end_ms: int = Field(..., ge=0)
    text: str
    speaker: str | None = None
    speaker_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class ChunkingOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_chunk_duration_ms: int | None = Field(default=None, gt=0)
    max_chunk_chars: int | None = Field(default=None, gt=0)
    max_chunk_tokens: int | None = Field(default=None, gt=0)
    overlap_duration_ms: int | None = Field(default=None, ge=0)
    overlap_segments: int | None = Field(default=None, ge=0)


class ChunkTranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    segments: list[TranscriptSegmentRequest] = Field(default_factory=list)
    options: ChunkingOptionsRequest | None = None


class ChunkResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_index: int
    text: str
    start_ms: int
    end_ms: int
    char_count: int
    token_count: int
    segment_index_start: int
    segment_index_end: int
    speakers: list[str] = Field(default_factory=list)


class ChunkTranscriptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_type: str
    strategy: str
    chunk_count: int
    chunks: list[ChunkResponse]
