"""Query parameter helpers for message list filters."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Query
from starlette import status


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _parse_uuid(value: str | None) -> UUID | None:
    raw = _blank(value)
    if raw is None:
        return None
    try:
        return UUID(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid UUID: {raw}",
        ) from exc


def _parse_int(value: str | None) -> int | None:
    raw = _blank(value)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid integer: {raw}",
        ) from exc


def _parse_datetime(value: str | None) -> datetime | None:
    raw = _blank(value)
    if raw is None:
        return None
    # datetime-local inputs often omit seconds / timezone.
    candidates = (raw, f"{raw}:00", f"{raw}:00+00:00", f"{raw}+00:00")
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Invalid datetime: {raw}",
    )


class MessageListQuery:
    """HTML filter form dependency.

    Empty strings from GET forms are treated as unset. Typed parsing is done
    manually so FastAPI does not 422 on blank optional fields.
    """

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: str | None = Query(None),
        # Avoid name clash with path param /messages/{ingress_message_id}
        filter_ingress_message_id: str | None = Query(
            None,
            alias="filter_ingress_message_id",
            description="Filter by internal ingress message UUID",
        ),
        chat_id: str | None = Query(None),
        message_id: str | None = Query(None),
        telegram_user_id: str | None = Query(None),
        conversation_status: str | None = Query(None),
        attachment_status: str | None = Query(None),
        has_attachment: str | None = Query(
            None,
            description="true|false|empty for any",
        ),
        failed_only: str | None = Query(None),
        created_from: str | None = Query(None),
        created_to: str | None = Query(None),
        q: str | None = Query(None, description="Text search"),
    ) -> None:
        self.page = page
        parsed_page_size = _parse_int(page_size)
        self.page_size = parsed_page_size if parsed_page_size and parsed_page_size > 0 else None
        self.filter_ingress_message_id = _parse_uuid(filter_ingress_message_id)
        self.chat_id = _parse_int(chat_id)
        self.message_id = _parse_int(message_id)
        self.telegram_user_id = _parse_int(telegram_user_id)
        self.conversation_status = _blank(conversation_status)
        self.attachment_status = _blank(attachment_status)
        has_raw = _blank(has_attachment)
        if has_raw is None:
            self.has_attachment: bool | None = None
        else:
            self.has_attachment = has_raw.lower() == "true"
        self.failed_only = (failed_only or "").lower() in {"true", "1", "on", "yes"}
        self.created_from = _parse_datetime(created_from)
        self.created_to = _parse_datetime(created_to)
        self.q = _blank(q)
