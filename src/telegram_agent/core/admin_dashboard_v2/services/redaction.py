from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import PurePath
from typing import Any


_SECRET_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
    "database_url",
    "api_key",
    "credential",
    "private_key",
)

_SENSITIVE_TEXT_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*)([^,;\r\n]+)"), r"\1<redacted>"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"), "<telegram-token-redacted>"),
    (re.compile(r"://[^/\s:@]+:[^@/\s]+@"), "://<credentials>@"),
)


def mask_identifier(value: str | None) -> str | None:
    if not value:
        return value
    if len(value) <= 10:
        return "••••"
    return f"{value[:4]}…{value[-4:]}"


def mask_path(value: str | None) -> str | None:
    if not value:
        return value
    return f"<masked>/{PurePath(value).name}"


def sanitize_payload(value: Any, *, maximum_bytes: int) -> Any:
    sanitized = _sanitize(value)
    encoded = json.dumps(sanitized, default=str, ensure_ascii=False)
    if len(encoded.encode("utf-8")) <= maximum_bytes:
        return sanitized
    return {
        "_truncated": True,
        "preview": encoded.encode("utf-8")[:maximum_bytes].decode("utf-8", errors="ignore"),
    }


def sanitize_trace_data(data: dict[str, Any], *, maximum_bytes: int) -> dict[str, Any]:
    sanitized = _sanitize(data)
    assert isinstance(sanitized, dict)
    return sanitize_payload(sanitized, maximum_bytes=maximum_bytes)


def sanitize_text(value: str) -> str:
    result = value
    for pattern, replacement in _SENSITIVE_TEXT_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _sanitize(value: Any, *, key: str = "") -> Any:
    normalized_key = key.lower()
    if any(part in normalized_key for part in _SECRET_KEY_PARTS):
        return "<redacted>"
    if "file_id" in normalized_key or "file_unique_id" in normalized_key:
        return mask_identifier(str(value)) if value is not None else None
    if "local_path" in normalized_key or normalized_key == "path":
        return mask_path(str(value)) if value is not None else None
    if normalized_key == "locked_by" and value is not None:
        return "<worker masked>"
    if isinstance(value, Mapping):
        return {str(item_key): _sanitize(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value
