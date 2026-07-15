from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from telegram_agent.core.admin_dashboard_v2.api.v1.dependencies import (
    get_message_listing_service,
    get_message_trace_service,
)
from telegram_agent.core.admin_dashboard_v2.common.exceptions import (
    FilterUnavailableError,
    InvalidCursorError,
)
from telegram_agent.core.admin_dashboard_v2.common.types import (
    MessageListFilters,
    MessagePageView,
)
from telegram_agent.core.admin_dashboard_v2.security.authentication import require_admin
from telegram_agent.core.admin_dashboard_v2.services.message_listing import MessageListingService
from telegram_agent.core.admin_dashboard_v2.services.message_trace import MessageTraceQueryService


logger = logging.getLogger(__name__)
router = APIRouter(tags=["messages"])


@router.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    return RedirectResponse(url="/messages", status_code=302)


@router.get("/messages", response_class=HTMLResponse)
async def list_messages(
    request: Request,
    admin: Annotated[str, Depends(require_admin)],
    listing_service: Annotated[MessageListingService, Depends(get_message_listing_service)],
    trace_service: Annotated[MessageTraceQueryService, Depends(get_message_trace_service)],
    selected: Annotated[UUID | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=250)] = None,
    chat_id: str | None = None,
    message_id: str | None = None,
    update_id: str | None = None,
    telegram_user_id: str | None = None,
    ingress_message_id: str | None = None,
    runtime_group_id: str | None = None,
    content_job_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    ingress_status: str | None = None,
    attachment_status: str | None = None,
    attachment_type: str | None = None,
    has_attachment: str | None = None,
    content_status: str | None = None,
    runtime_status: str | None = None,
    failed_only: bool = False,
) -> HTMLResponse:
    filters = MessageListFilters(
        chat_id=_optional_int(chat_id, "chat_id"),
        message_id=_optional_int(message_id, "message_id"),
        update_id=_optional_int(update_id, "update_id"),
        telegram_user_id=_optional_int(telegram_user_id, "telegram_user_id"),
        ingress_message_id=_optional_uuid(ingress_message_id, "ingress_message_id"),
        runtime_group_id=_optional_uuid(runtime_group_id, "runtime_group_id"),
        content_job_id=_optional_uuid(content_job_id, "content_job_id"),
        date_from=_optional_datetime(
            date_from,
            "date_from",
            request.app.state.dashboard_settings.display_timezone,
        ),
        date_to=_optional_datetime(
            date_to,
            "date_to",
            request.app.state.dashboard_settings.display_timezone,
        ),
        ingress_status=_empty_to_none(ingress_status),
        attachment_status=_empty_to_none(attachment_status),
        attachment_type=_empty_to_none(attachment_type),
        has_attachment=_optional_bool(has_attachment, "has_attachment"),
        content_status=_empty_to_none(content_status),
        runtime_status=_empty_to_none(runtime_status),
        failed_only=failed_only,
    )
    return await _render(
        request=request,
        admin=admin,
        listing_service=listing_service,
        trace_service=trace_service,
        filters=filters,
        selected=selected,
        cursor=cursor,
        page_size=page_size,
    )


@router.get("/messages/{ingress_message_id}", response_class=HTMLResponse)
async def selected_message(
    ingress_message_id: UUID,
    request: Request,
    admin: Annotated[str, Depends(require_admin)],
    listing_service: Annotated[MessageListingService, Depends(get_message_listing_service)],
    trace_service: Annotated[MessageTraceQueryService, Depends(get_message_trace_service)],
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    page_size: Annotated[int | None, Query(ge=1, le=250)] = None,
    chat_id: int | None = None,
    message_id: int | None = None,
    telegram_user_id: int | None = None,
) -> HTMLResponse:
    filters = MessageListFilters(
        chat_id=chat_id,
        message_id=message_id,
        telegram_user_id=telegram_user_id,
    )
    return await _render(
        request=request,
        admin=admin,
        listing_service=listing_service,
        trace_service=trace_service,
        filters=filters,
        selected=ingress_message_id,
        cursor=cursor,
        page_size=page_size,
    )


async def _render(
    *,
    request: Request,
    admin: str,
    listing_service: MessageListingService,
    trace_service: MessageTraceQueryService,
    filters: MessageListFilters,
    selected: UUID | None,
    cursor: str | None,
    page_size: int | None,
) -> HTMLResponse:
    settings = request.app.state.dashboard_settings
    error: str | None = None
    status_code = 200
    try:
        page = await listing_service.list_messages(
            filters=filters,
            cursor_value=cursor,
            page_size=page_size or settings.default_page_size,
        )
    except InvalidCursorError as exc:
        page = MessagePageView(items=(), next_cursor=None, scanned_count=0, scan_limit_reached=False)
        error = str(exc)
        status_code = 400
    except FilterUnavailableError as exc:
        page = MessagePageView(items=(), next_cursor=None, scanned_count=0, scan_limit_reached=False)
        error = str(exc)
        status_code = 503

    trace = await trace_service.get_trace(selected) if selected is not None else None
    query_items = _filter_query_items(request)
    query_without_cursor = [(key, value) for key, value in query_items if key not in {"cursor", "selected"}]
    filter_query = urlencode(query_without_cursor)
    next_url = None
    if page.next_cursor:
        next_url = "/messages?" + urlencode(query_without_cursor + [("cursor", page.next_cursor)])
    logger.info(
        "Dashboard message view",
        extra={
            "admin_username": admin,
            "selected_ingress_message_id": str(selected) if selected else None,
            "result_count": len(page.items),
            "partial_sources": [state.source for state in page.source_states if not state.available],
        },
    )
    templates: Jinja2Templates = request.app.state.templates
    return templates.TemplateResponse(
        request=request,
        name="messages/index.html",
        context={
            "admin_username": admin,
            "page": page,
            "trace": trace,
            "filters": filters,
            "filter_query": filter_query,
            "next_url": next_url,
            "error": error,
            "display_timezone": settings.display_timezone,
        },
        status_code=status_code,
    )


def _filter_query_items(request: Request) -> list[tuple[str, str]]:
    return [(key, value) for key, value in request.query_params.multi_items() if value != ""]


def _empty_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(value: str | None, field_name: str) -> int | None:
    normalized = _empty_to_none(value)
    if normalized is None:
        return None
    try:
        return int(normalized)
    except ValueError as exc:
        raise _invalid_filter(field_name) from exc


def _optional_uuid(value: str | None, field_name: str) -> UUID | None:
    normalized = _empty_to_none(value)
    if normalized is None:
        return None
    try:
        return UUID(normalized)
    except ValueError as exc:
        raise _invalid_filter(field_name) from exc


def _optional_datetime(
    value: str | None,
    field_name: str,
    timezone_name: str,
) -> datetime | None:
    normalized = _empty_to_none(value)
    if normalized is None:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise _invalid_filter(field_name) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed


def _optional_bool(value: str | None, field_name: str) -> bool | None:
    normalized = _empty_to_none(value)
    if normalized is None:
        return None
    lowered = normalized.casefold()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    raise _invalid_filter(field_name)


def _invalid_filter(field_name: str) -> HTTPException:
    return HTTPException(status_code=422, detail=f"Invalid {field_name} filter")
