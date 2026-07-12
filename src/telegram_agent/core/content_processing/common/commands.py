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


@dataclass(frozen=True)
class RecordMediaDownloadCommand:
    job_id: UUID
    media_asset_id: UUID
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


class NotifyAttachmentProcessingResultCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    ingress_attachment_id: UUID
    status: AttachmentProcessingResultStatus
    transcribed_text: str | None = None
