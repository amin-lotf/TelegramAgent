import re
from datetime import datetime, timezone


def utcnow() -> datetime:
    # Ensures tz-aware "now"
    return datetime.now(timezone.utc)


def seconds_to_ms(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(value * 1000))


def clean_error_message(message: str, max_length: int = 200) -> str:
    message = message.replace("\\n", "\n")
    message = message.strip()

    # Remove repeated yt-dlp prefix if you already add your own ❌ prefix
    message = re.sub(r"^ERROR:\s*", "", message, flags=re.IGNORECASE)

    # Make it one clean line for Telegram notification header
    message = re.sub(r"\s+", " ", message)

    return message[:max_length]


