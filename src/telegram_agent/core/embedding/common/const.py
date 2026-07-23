"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS: int | None = None
DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS = 60.0
DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS = 5.0
DEFAULT_OPENAI_MAX_RETRIES = 2
DEFAULT_MAX_EMBEDDING_BATCH_SIZE = 256
OPENAI_PROVIDER = "openai"
