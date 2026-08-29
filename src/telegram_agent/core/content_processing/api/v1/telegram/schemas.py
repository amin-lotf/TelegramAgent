from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

    @model_validator(mode="after")
    def require_request_message_id_for_secondary_work(
        self,
    ) -> "AcceptVideoDownloadRequest":
        if (
            self.requested_subtitle_language or self.requested_dub_language
        ) and self.reply_to_message_id is None:
            raise ValueError(
                "reply_to_message_id is required for dub/subtitle requests"
            )
        return self


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


class CancelAllSecondaryTasksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    telegram_user_id: int
    chat_id: int
    cutoff_message_id: int = Field(gt=0)


class CancelAllSecondaryTasksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "registered"
    cancellation_id: UUID
    cutoff_message_id: int
    matched_active_count: int
