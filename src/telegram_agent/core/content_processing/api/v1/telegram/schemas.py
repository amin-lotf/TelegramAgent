from uuid import UUID

from pydantic import BaseModel

from telegram_agent.core.common.types import TelegramAttachmentType


class CreateContentProcessingJobRequest(BaseModel):
    ingress_message_id: UUID
    ingress_attachment_id: UUID
    telegram_user_id: int
    telegram_file_id: str
    telegram_file_unique_id: str | None = None
    attachment_type:  TelegramAttachmentType
    callback_required: bool = True
    idempotency_key: str