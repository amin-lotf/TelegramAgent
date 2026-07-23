from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from telegram_agent.core.content_processing.common.types import JobStatus


class CreateTelegramJobResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    created: bool


class CreateDownloadRequestResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    created: bool
    media_type: str


@dataclass(frozen=True)
class OutboxDispatchResult:
    claimed: int = 0
    published: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0


@dataclass(frozen=True)
class JobExpectationSweepResult:
    claimed: int = 0
    timed_out: int = 0
    satisfied: int = 0
    extended: int = 0
    recovered_leases: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class TelegramDownloadContext:
    job_id: UUID
    media_asset_id: UUID
    telegram_file_id: str
    media_type: str


@dataclass(frozen=True)
class MediaDownloadResult:
    local_path: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True)
class MediaDemuxResult:
    audio_path: str
    audio_size_bytes: int
    audio_mime_type: str | None
    video_path: str
    video_size_bytes: int
    video_mime_type: str | None


@dataclass(frozen=True)
class TranscriptionContext:
    job_id: UUID
    media_asset_id: UUID
    local_path: Path
    mime_type: str | None


@dataclass(frozen=True)
class TranscriptionSegmentResult:
    start_ms: int
    end_ms: int
    text: str
    language: str | None
    language_probability: float | None
    speaker: str | None
    speaker_confidence: float | None


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None
    language_probability: float | None
    duration_ms: int | None
    segments: tuple[TranscriptionSegmentResult, ...]


@dataclass(frozen=True)
class ChunkingSegmentInput:
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: str | None
    speaker_confidence: float | None


@dataclass(frozen=True)
class ChunkingContext:
    job_id: UUID
    language: str | None
    duration_ms: int | None
    segments: tuple[ChunkingSegmentInput, ...]


@dataclass(frozen=True)
class ChunkResultItem:
    chunk_index: int
    text: str
    start_ms: int
    end_ms: int
    char_count: int
    token_count: int
    segment_index_start: int
    segment_index_end: int
    speakers: tuple[str, ...]


@dataclass(frozen=True)
class ChunkingResult:
    content_type: str
    strategy: str
    chunk_count: int
    chunks: tuple[ChunkResultItem, ...]


@dataclass(frozen=True)
class StageExecutionResult:
    retryable: bool = False
    error_message: str | None = None


@dataclass(frozen=True)
class TelegramFile:
    path: str
    size_bytes: int | None


@dataclass(frozen=True)
class TelegramFileStream:
    mime_type: str | None
    content_length: int | None
    chunks: Iterator[bytes]
