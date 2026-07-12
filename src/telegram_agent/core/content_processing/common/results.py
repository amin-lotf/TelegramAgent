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


@dataclass(frozen=True)
class OutboxDispatchResult:
    claimed: int = 0
    published: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0


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
