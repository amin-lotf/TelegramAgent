from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from telegram_agent.core.common.types import TelegramAttachmentType


class CreateContentProcessingJobRequest(BaseModel):
    ingress_message_id: UUID
    ingress_attachment_id: UUID
    telegram_user_id: int
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    attachment_type: TelegramAttachmentType
    callback_required: bool = True
    idempotency_key: str


class _DownloadHandoffBase(BaseModel):
    """Common fields for agent-runtime → content-processing download handoffs."""

    model_config = ConfigDict(extra="forbid")

    chat_id: int
    telegram_user_id: int
    group_id: UUID
    agent_message_id: UUID
    media_ingress_message_id: UUID
    assistant_text: str = Field(min_length=1, max_length=2_000)
    # Telegram message_id of the user request to reply to on delivery.
    reply_to_message_id: int | None = None


class AcceptVideoDownloadRequest(_DownloadHandoffBase):
    requested_subtitle_language: str | None = Field(default=None, max_length=64)
    requested_dub_language: str | None = Field(default=None, max_length=64)


class AcceptAudioDownloadRequest(_DownloadHandoffBase):
    requested_language: str | None = Field(default=None, max_length=64)


class AcceptDocumentDownloadRequest(_DownloadHandoffBase):
    requested_format: str | None = Field(default=None, max_length=64)


class AcceptDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    accepted: bool = True
    media_type: str
    job_id: UUID


class CancelDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_user_id: int


class CancelDownloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    cancelled: bool
    job_id: UUID
