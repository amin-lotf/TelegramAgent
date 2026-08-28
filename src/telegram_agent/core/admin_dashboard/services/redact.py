"""Mask sensitive fields before rendering."""
from __future__ import annotations

from pathlib import PurePath, PurePosixPath, PureWindowsPath


def mask_path(path: str | None, *, enabled: bool) -> str | None:
    if path is None or not enabled:
        return path
    pure: PurePath = PurePosixPath(path)
    if len(pure.parts) <= 1:
        pure = PureWindowsPath(path)
    name = pure.name or path
    parent = pure.parent.name if pure.parent and pure.parent.name else "…"
    return f"…/{parent}/{name}"


def mask_text(text: str | None, *, enabled: bool, max_len: int = 80) -> str | None:
    if text is None:
        return None
    if not enabled:
        return text
    if len(text) <= 4:
        return "****"
    return text[:2] + "…" + text[-1:]


def text_preview(text: str | None, *, max_len: int = 80, mask: bool = False) -> str:
    if not text:
        return ""
    value = mask_text(text, enabled=mask) or ""
    if len(value) <= max_len:
        return value
    return value[: max_len - 1] + "…"
