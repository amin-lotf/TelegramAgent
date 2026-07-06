from pydantic import BaseModel, Field


class TelegramVerifyRequest(BaseModel):
    telegram_user_id: int = Field(..., description="Telegram user ID from message.from.id")
    chat_id: int = Field(..., description="Telegram chat ID from message.chat.id")

    password: str = Field(..., min_length=1)

    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_bot: bool = False
    language_code: str | None = None


class TelegramVerifyResponse(BaseModel):
    verified: bool
    message: str


class TelegramCheckRequest(BaseModel):
    telegram_user_id: int = Field(..., description="Telegram user ID from message.from.id")


class TelegramCheckResponse(BaseModel):
    verified: bool
    message: str | None = None

