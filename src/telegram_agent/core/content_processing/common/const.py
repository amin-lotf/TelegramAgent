"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

from zoneinfo import ZoneInfo

DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_TELEGRAM_AUTH_BASE_URL="http://localhost:8000/api/v1/telegram-auth"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"

