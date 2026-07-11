"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

from zoneinfo import ZoneInfo

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_WHISPERX_MODEL = "large-v3"
DEFAULT_WHISPERX_BASE_URL = "http://whisperx:8000/v1"