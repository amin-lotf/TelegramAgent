# telegram_agent/core/telegram_ingress/application/commands.py

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import TelegramUserRequest
from telegram_agent.core.telegram_ingress.common.types import TelegramAttachmentType


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