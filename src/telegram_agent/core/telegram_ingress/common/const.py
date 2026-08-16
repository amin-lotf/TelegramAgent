"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

from zoneinfo import ZoneInfo

DEFAULT_SQLALCHEMY_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_TELEGRAM_AUTH_BASE_URL="http://localhost:8000/api/v1/telegram-auth"
DEFAULT_CONTENT_PROCESSING_BASE_URL="http://localhost:8000/api/v1/telegram/attachments"
DEFAULT_AGENT_RUNTIME_BASE_URL = "http://localhost:8000/api/v1/agent-runtime"
DEFAULT_AGENT_RUNTIME_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_TELEGRAM_API_BASE_URL = "https://api.telegram.org"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE = 50
DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS = 60
DEFAULT_OUTBOX_RETRY_BASE_SECONDS = 5
DEFAULT_OUTBOX_RETRY_MAX_SECONDS = 300
