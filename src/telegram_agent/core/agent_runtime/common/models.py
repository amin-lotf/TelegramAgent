from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.llm_gateway.common.schemas import (
    IntentClassificationResponse,
    MessageGroupingResponse,
)

# Shared structured-output contracts owned by llm_gateway; re-exported for domain use.
CoordinatorDecision = MessageGroupingResponse
IntentClassificationDecision = IntentClassificationResponse


class CoordinatorMessageView(BaseModel):
    """Message projection supplied to the message-grouping prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    message_id: int
    reply_message_id: int | None = None
    text: str | None = None
    attachment_type: TelegramAttachmentType | None = None
    group_number: int | None = None


class IntentClassifierMessageView(BaseModel):
    """Message projection supplied to the intent-classification prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    message_id: int
    text: str | None = None
    attachment_type: TelegramAttachmentType | None = None
