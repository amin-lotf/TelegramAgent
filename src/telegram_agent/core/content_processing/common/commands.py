from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator
from telegram_agent.core.common.types import TelegramAttachmentType


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


