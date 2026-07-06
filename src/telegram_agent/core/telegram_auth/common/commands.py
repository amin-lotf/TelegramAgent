from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class VerifyTelegramUserCommand:
    telegram_user_id: int
    chat_id: int
    password: str | None = None
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    is_bot: bool | None = None
    language_code: str | None = None