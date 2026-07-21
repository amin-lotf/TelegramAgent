"""Default (non-secret) configuration values used by BaseSettings."""
from __future__ import annotations

DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:5678,"
    "https://ops.fatolai.com,"
)
DEFAULT_LOG_LEVEL = "DEBUG"
DEFAULT_TARGET_CHUNK_DURATION_MS = 60_000
DEFAULT_MAX_CHUNK_CHARS = 2_000
DEFAULT_MAX_CHUNK_TOKENS = 512
DEFAULT_OVERLAP_DURATION_MS = 8_000
DEFAULT_OVERLAP_SEGMENTS = 1
TRANSCRIPT_SEGMENT_WINDOW_STRATEGY = "transcript_segment_window_v1"
