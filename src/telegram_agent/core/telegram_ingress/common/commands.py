# telegram_agent/core/telegram_ingress/application/commands.py

from __future__ import annotations

from typing import Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import TelegramUserRequest
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage, Attachment


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
    def from_user_message(
            cls,
            user_message: UserMessage,
            *,
            callback_required: bool = True,
    ) -> Self:
        attachment = user_message.attachment

        if attachment is None:
            raise ValueError("Cannot process user message without attachment.")

        attachment_type = cast(TelegramAttachmentType, attachment.type)
        attachment_id = cast(UUID, attachment.id)

        return cls(
            ingress_message_id=cast(UUID, user_message.id),
            ingress_attachment_id=attachment_id,
            telegram_user_id=cast(int, user_message.telegram_user_id),
            telegram_file_id=cast(str, attachment.file_id),
            telegram_file_unique_id=cast(str | None, attachment.file_unique_id),
            attachment_type=attachment_type,
            callback_required=callback_required,
            idempotency_key=(
                f"telegram-ingress:"
                f"process-attachment:"
                f"{attachment_type.value}:"
                f"{attachment_id}:"
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

    # Telegram text OR caption
    text: str | None = None


    attachment: CreateAttachmentCommand | None = None

    @model_validator(mode="after")
    def validate_message_content(self) -> Self:
        if self.text is None and self.attachment is None:
            raise ValueError("User message must have either text or attachment.")

        return self

    @classmethod
    def from_request(cls, payload: TelegramUserRequest) -> Self:
        attachment = None

        if payload.attachment is not None:
            attachment = CreateAttachmentCommand(
                type=payload.attachment.type,
                file_id=payload.attachment.file_id,
                file_unique_id=payload.attachment.file_unique_id,
            )

        return cls(
            update_id=payload.update_id,
            telegram_user_id=payload.telegram_user_id,
            chat_id=payload.chat_id,
            message_id=payload.message_id,
            reply_message_id=payload.reply_to_message_id,
            text=payload.text or payload.caption,
            attachment=attachment,
        )