"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

from telegram_agent.core.common.types import TelegramAttachmentType

DEFAULT_SQLALCHEMY_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)

# One of these attachment types per conversation group. Voice/video_note are excluded
# (they are typically transcribed into text). Distinct from download-handler media types.
GROUP_EXCLUSIVE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VIDEO,
        TelegramAttachmentType.AUDIO,
        TelegramAttachmentType.DOCUMENT,
        TelegramAttachmentType.PHOTO,
    }
)
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_TELEGRAM_INGRESS_BASE_URL = "http://localhost:8000/api/v1/telegram-ingress"
DEFAULT_CONTENT_PROCESSING_BASE_URL = "http://localhost:8000/api/v1/telegram"
DEFAULT_LLM_GATEWAY_BASE_URL = "http://localhost:8000/v1"
DEFAULT_LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS = 30.0
DEFAULT_LLM_GATEWAY_DOWNLOAD_AGENT_TIMEOUT_SECONDS = 180.0
DEFAULT_TELEGRAM_INGRESS_REQUEST_TIMEOUT_SECONDS = 5.0
DEFAULT_CONTENT_PROCESSING_REQUEST_TIMEOUT_SECONDS = 10.0
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE = 20
DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS = 60
DEFAULT_OUTBOX_RETRY_BASE_SECONDS = 5
DEFAULT_OUTBOX_RETRY_MAX_SECONDS = 300
# Max recorded failures before a retryable outbox is promoted to permanent.
DEFAULT_OUTBOX_MAX_ATTEMPTS = 5
DEFAULT_COORDINATION_MESSAGE_BATCH_SIZE = 20
DEFAULT_COORDINATION_RECENT_WINDOW_SIZE = 10
DEFAULT_COORDINATION_CLAIM_LEASE_SECONDS = 300
