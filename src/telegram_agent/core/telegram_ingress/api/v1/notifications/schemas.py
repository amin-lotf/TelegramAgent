from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: int
    telegram_user_id: int
    text: str = Field(min_length=1, max_length=4_096)
    group_id: UUID | None = None
    ingress_message_id: UUID | None = None
    reply_to_message_id: int | None = None

    @model_validator(mode="after")
    def require_reply_target_hint(self) -> "UserNotificationRequest":
        # Either is enough; both allowed. Neither is still accepted (non-reply send).
        return self


class UserNotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "sent"
    telegram_message_id: int
