from pydantic import ConfigDict, BaseModel

from telegram_agent.core.telegram_ingress.common.types import TelegramAttachmentType


class TelegramAttachmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: TelegramAttachmentType
    file_id: str
    file_unique_id: str | None = None


class TelegramUserRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    telegram_user_id: int
    chat_id: int
    message_id: int
    update_id: int | None = None

    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None


    reply_to_message_id: int | None = None

    text: str | None = None
    caption: str | None = None

    attachment: TelegramAttachmentPayload | None = None
