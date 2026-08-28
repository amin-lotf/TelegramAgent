"""Default (non-secret) configuration values for the admin dashboard."""
from __future__ import annotations

DEFAULT_TELEGRAM_INGRESS_RO_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)
DEFAULT_CONTENT_PROCESSING_RO_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)
DEFAULT_AGENT_RUNTIME_RO_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)
DEFAULT_TELEGRAM_AUTH_RO_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent"
)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_SESSION_COOKIE_NAME = "admin_dashboard_session"
DEFAULT_SESSION_HTTPS_ONLY = False

DEFAULT_DB_QUERY_TIMEOUT_SECONDS = 3.0
DEFAULT_DB_CONNECT_TIMEOUT_SECONDS = 2.0
DEFAULT_DB_POOL_SIZE = 2
DEFAULT_DB_POOL_MAX_OVERFLOW = 0

DEFAULT_LIST_PAGE_SIZE = 50
DEFAULT_LIST_MAX_PAGE_SIZE = 200
DEFAULT_WORKFLOW_POLL_INTERVAL_SECONDS = 10

DEFAULT_MASK_MEDIA_PATHS = True
DEFAULT_MASK_MESSAGE_TEXT = False
DEFAULT_ENABLE_AUTH_DB_ENRICHMENT = True

DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_ALLOWED_ORIGINS = ""
