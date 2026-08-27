from __future__ import annotations

import html
import re
from collections.abc import Callable
from typing import Any

# LLMs and English TN frontends sometimes emit XML/HTML entities for apostrophes
# ("It &apos;s") and split contractions ("It 's", "do n't").
_NT_CONTRACTION_RE = re.compile(
    r"\b([A-Za-z]+)\s+n\s*['’]\s*t\b",
    flags=re.IGNORECASE,
)
_APOSTROPHE_CONTRACTION_RE = re.compile(
    r"\b([A-Za-z]+)\s+['’]\s*(s|t|re|ve|ll|d|m)\b",
    flags=re.IGNORECASE,
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")


def sanitize_spoken_text(text: str) -> str:
    """Turn HTML entities into real characters and rejoin split contractions."""
    if not text:
        return text
    cleaned = html.unescape(text)
    cleaned = _NT_CONTRACTION_RE.sub(r"\1n't", cleaned)
    cleaned = _APOSTROPHE_CONTRACTION_RE.sub(r"\1'\2", cleaned)
    return _MULTI_SPACE_RE.sub(" ", cleaned)


def sanitize_normalized_result(result: Any) -> Any:
    if isinstance(result, str):
        return sanitize_spoken_text(result)
    if isinstance(result, list):
        return [
            sanitize_spoken_text(item) if isinstance(item, str) else item
            for item in result
        ]
    return result


def wrap_text_normalize(original: Callable[..., Any]) -> Callable[..., Any]:
    """Run a text-normalize function, then strip entity leaks from the result."""

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        return sanitize_normalized_result(original(*args, **kwargs))

    wrapped.__name__ = getattr(original, "__name__", "text_normalize")
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    return wrapped
