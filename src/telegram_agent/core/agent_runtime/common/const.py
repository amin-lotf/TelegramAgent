"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

DEFAULT_SQLALCHEMY_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_TELEGRAM_INGRESS_BASE_URL = "http://localhost:8000/api/v1/telegram-ingress"
DEFAULT_CONTENT_PROCESSING_BASE_URL = "http://localhost:8000/api/v1/telegram/attachments"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE = 20
DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS = 60
DEFAULT_OUTBOX_RETRY_BASE_SECONDS = 5
DEFAULT_OUTBOX_RETRY_MAX_SECONDS = 300
DEFAULT_COORDINATION_MESSAGE_BATCH_SIZE = 20
DEFAULT_COORDINATION_RECENT_WINDOW_SIZE = 10
DEFAULT_COORDINATION_CLAIM_LEASE_SECONDS = 300
