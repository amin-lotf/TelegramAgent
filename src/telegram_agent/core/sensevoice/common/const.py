"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_SENSEVOICE_MODEL = "iic/SenseVoiceSmall"
DEFAULT_SENSEVOICE_BASE_URL = "http://sensevoice:8000/api/v1"
