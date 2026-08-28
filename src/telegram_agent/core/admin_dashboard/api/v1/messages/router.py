"""HTML routes for message list and detail views."""
from __future__ import annotations

import json
import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette import status

from telegram_agent.core.admin_dashboard.api.v1.auth import AdminUser
from telegram_agent.core.admin_dashboard.api.v1.dependencies import (
    get_message_list_service,
    get_message_trace_service,
    get_settings,
)
from telegram_agent.core.admin_dashboard.api.v1.messages.schemas import MessageListQuery
from telegram_agent.core.admin_dashboard.common.settings import Settings
from telegram_agent.core.admin_dashboard.services.message_list import MessageListService
from telegram_agent.core.admin_dashboard.services.message_trace import MessageTraceService

router = APIRouter(tags=["messages"])


def _templates(request: Request) -> Jinja2Templates:
    return request.app.state.templates


@router.get("/", response_class=HTMLResponse)
async def root_redirect() -> RedirectResponse:
    return RedirectResponse(url="/messages", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/messages", response_class=HTMLResponse)
async def list_messages(
    request: Request,
    admin_user: AdminUser,
    query: Annotated[MessageListQuery, Depends()],
    list_service: Annotated[MessageListService, Depends(get_message_list_service)],
) -> HTMLResponse:
    result = await list_service.list_messages(
        page=query.page,
        page_size=query.page_size,
        ingress_message_id=query.filter_ingress_message_id,
        chat_id=query.chat_id,
        message_id=query.message_id,
        telegram_user_id=query.telegram_user_id,
        conversation_status=query.conversation_status,
        attachment_status=query.attachment_status,
        has_attachment=query.has_attachment,
        failed_only=query.failed_only,
        created_from=query.created_from,
        created_to=query.created_to,
        text_query=query.q,
    )
    total_pages = max(1, math.ceil(result.total / result.page_size)) if result.total else 1
    return _templates(request).TemplateResponse(
        request,
        "messages/list.html",
        {
            "admin_user": admin_user,
            "result": result,
            "query": query,
            "total_pages": total_pages,
            "selected_id": None,
            "trace": None,
            "db_status": {},
        },
    )


@router.get("/messages/{ingress_message_id}", response_class=HTMLResponse)
async def message_detail(
    request: Request,
    ingress_message_id: UUID,
    admin_user: AdminUser,
    query: Annotated[MessageListQuery, Depends()],
    list_service: Annotated[MessageListService, Depends(get_message_list_service)],
    trace_service: Annotated[MessageTraceService, Depends(get_message_trace_service)],
    app_settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    result = await list_service.list_messages(
        page=query.page,
        page_size=query.page_size,
        ingress_message_id=query.filter_ingress_message_id,
        chat_id=query.chat_id,
        message_id=query.message_id,
        telegram_user_id=query.telegram_user_id,
        conversation_status=query.conversation_status,
        attachment_status=query.attachment_status,
        has_attachment=query.has_attachment,
        failed_only=query.failed_only,
        created_from=query.created_from,
        created_to=query.created_to,
        text_query=query.q,
    )
    trace = await trace_service.get_trace(ingress_message_id)
    total_pages = max(1, math.ceil(result.total / result.page_size)) if result.total else 1

    raw_payload = None
    if trace.ingress_outbox is not None:
        raw_payload = json.dumps(trace.ingress_outbox.payload, indent=2, default=str)

    db_status = {
        name.value: status.value for name, status in trace.db_availability.items()
    }
    return _templates(request).TemplateResponse(
        request,
        "messages/detail.html",
        {
            "admin_user": admin_user,
            "result": result,
            "query": query,
            "total_pages": total_pages,
            "selected_id": ingress_message_id,
            "trace": trace,
            "raw_payload": raw_payload,
            "db_status": db_status,
            "workflow_poll_interval_seconds": (
                app_settings.workflow_poll_interval_seconds
            ),
        },
    )


@router.get(
    "/messages/{ingress_message_id}/workflows",
    response_class=HTMLResponse,
)
async def message_workflows_fragment(
    request: Request,
    ingress_message_id: UUID,
    admin_user: AdminUser,
    trace_service: Annotated[MessageTraceService, Depends(get_message_trace_service)],
) -> HTMLResponse:
    trace = await trace_service.get_trace(ingress_message_id)
    db_status = {
        name.value: status.value for name, status in trace.db_availability.items()
    }
    return _templates(request).TemplateResponse(
        request,
        "messages/_workflows.html",
        {
            "admin_user": admin_user,
            "trace": trace,
            "db_status": db_status,
        },
    )
