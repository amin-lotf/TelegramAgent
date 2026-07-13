from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus


class ProcessAttachmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    ingress_attachment_id: UUID
    telegram_user_id: int
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    attachment_type: TelegramAttachmentType
    callback_required: bool = True
    idempotency_key: str

    @classmethod
    def create(
        cls,
        *,
        ingress_message_id: UUID,
        ingress_attachment_id: UUID,
        telegram_user_id: int,
        telegram_file_id: str,
        telegram_file_unique_id: str | None,
        attachment_type: TelegramAttachmentType,
        callback_required: bool = True,
    ) -> Self:
        return cls(
            ingress_message_id=ingress_message_id,
            ingress_attachment_id=ingress_attachment_id,
            telegram_user_id=telegram_user_id,
            telegram_file_id=telegram_file_id,
            telegram_file_unique_id=telegram_file_unique_id,
            attachment_type=attachment_type,
            callback_required=callback_required,
            idempotency_key=(
                f"telegram-ingress:"
                f"process-attachment:"
                f"{attachment_type.value}:"
                f"{ingress_attachment_id}:"
                f"v1"
            ),
        )


class CreateAttachmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: TelegramAttachmentType
    file_id: str
    file_unique_id: str | None = None


class CreateUserMessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    update_id: int | None = None
    telegram_user_id: int
    chat_id: int
    message_id: int
    reply_message_id: int | None = None
    text: str | None = None
    attachment: CreateAttachmentCommand | None = None

    @model_validator(mode="after")
    def validate_message_content(self) -> Self:
        if self.text is None and self.attachment is None:
            raise ValueError("User message must have either text or attachment.")
        return self


class ApplyAttachmentProcessingResultCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    ingress_attachment_id: UUID
    status: AttachmentProcessingResultStatus
    transcribed_text: str | None = None


class RuntimeAttachmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_attachment_id: UUID
    type: TelegramAttachmentType
    status: AttachmentStatus
    file_id: str
    file_unique_id: str | None = None


class RuntimeMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    telegram_user_id: int
    message_id: int
    reply_message_id: int | None = None
    text: str | None = None
    attachment: RuntimeAttachmentPayload | None = None


class RuntimeMessageBatchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    messages: tuple[RuntimeMessagePayload, ...] = Field(min_length=1)
