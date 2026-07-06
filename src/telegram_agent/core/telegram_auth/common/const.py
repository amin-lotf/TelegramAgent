"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

from zoneinfo import ZoneInfo

DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
