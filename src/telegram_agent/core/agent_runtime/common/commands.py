from __future__ import annotations

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from telegram_agent.core.common.types import TelegramAttachmentType


class IngestAttachmentCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_attachment_id: UUID
    type: TelegramAttachmentType
    status: str
    file_id: str
    file_unique_id: str | None = None


class IngestMessageCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    telegram_user_id: int
    message_id: int
    reply_message_id: int | None = None
    text: str | None = None
    attachment: IngestAttachmentCommand | None = None

    @model_validator(mode="after")
    def validate_content(self) -> Self:
        if self.text is None and self.attachment is None:
            raise ValueError("Runtime message must contain text or an attachment.")
        return self


class IngestMessageBatchCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    chat_id: int
    idempotency_key: str = Field(min_length=1)
    messages: tuple[IngestMessageCommand, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_message_order(self) -> Self:
        message_ids = [message.message_id for message in self.messages]
        if message_ids != sorted(message_ids) or len(message_ids) != len(set(message_ids)):
            raise ValueError(
                "Runtime messages must be in strictly increasing message order."
            )
        return self
