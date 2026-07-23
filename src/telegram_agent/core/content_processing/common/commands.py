from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)


class CreateTelegramJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    ingress_attachment_id: UUID
    telegram_user_id: int
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    attachment_type: TelegramAttachmentType
    callback_required: bool = True
    idempotency_key: str


class CreateDownloadRequestCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    telegram_user_id: int
    group_id: UUID
    agent_message_id: UUID
    media_ingress_message_id: UUID
    media_type: str
    assistant_text: str
    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    requested_language: str | None = None
    requested_format: str | None = None
    idempotency_key: str


@dataclass(frozen=True)
class RecordMediaDownloadCommand:
    job_id: UUID
    media_asset_id: UUID
    local_path: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True)
class UpsertDerivedMediaAssetCommand:
    job_id: UUID
    role: str
    media_type: str
    parent_asset_id: UUID
    local_path: str
    size_bytes: int
    mime_type: str | None


@dataclass(frozen=True)
class RecordTranscriptSegmentCommand:
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    language: str | None
    language_probability: float | None
    speaker: str | None
    speaker_confidence: float | None


@dataclass(frozen=True)
class RecordTranscriptCommand:
    job_id: UUID
    text: str
    language: str | None
    language_probability: float | None
    duration_ms: int | None
    segments: tuple[RecordTranscriptSegmentCommand, ...]


@dataclass(frozen=True)
class RecordContentChunkCommand:
    chunk_index: int
    text: str
    start_ms: int | None
    end_ms: int | None
    char_count: int
    token_count: int | None
    segment_index_start: int | None
    segment_index_end: int | None
    speakers: tuple[str, ...] | None
    strategy: str
    metadata: dict[str, object] | None = None


@dataclass(frozen=True)
class RecordContentChunksCommand:
    job_id: UUID
    content_type: str
    chunks: tuple[RecordContentChunkCommand, ...]


@dataclass(frozen=True)
class RecordChunkEmbeddingCommand:
    chunk_id: UUID
    provider: str
    model: str
    dimensions: int
    embedding: tuple[float, ...]


@dataclass(frozen=True)
class RecordChunkEmbeddingsCommand:
    job_id: UUID
    embeddings: tuple[RecordChunkEmbeddingCommand, ...]


class NotifyAttachmentProcessingResultCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    ingress_attachment_id: UUID
    status: AttachmentProcessingResultStatus
    transcribed_text: str | None = None
