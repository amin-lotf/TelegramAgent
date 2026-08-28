from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request

from telegram_agent.core.admin_dashboard.api.v1.auth import require_admin
from telegram_agent.core.admin_dashboard.api.v1.fastapi_app import _build_templates
from telegram_agent.core.admin_dashboard.api.v1.messages.router import (
    message_workflows_fragment,
    router,
)
from telegram_agent.core.admin_dashboard.common.types import (
    DbAvailability,
    DbName,
    OverallState,
)
from telegram_agent.core.admin_dashboard.services.view_models import MessageTrace
from telegram_agent.core.admin_dashboard.services.workflows import (
    build_workflow_collection,
)

from tests.admin_dashboard.test_workflows import _message, _request


class _TraceService:
    def __init__(self, trace: MessageTrace) -> None:
        self._trace = trace

    async def get_trace(self, _ingress_message_id):  # type: ignore[no-untyped-def]
        return self._trace


def _app() -> FastAPI:
    app = FastAPI()
    app.state.templates = _build_templates()
    app.include_router(router)
    return app


def _http_request(app: FastAPI, *, authenticated: bool = True) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
            "client": ("test", 1),
            "app": app,
            "session": {"admin_user": "admin"} if authenticated else {},
        }
    )


def _trace() -> MessageTrace:
    message = _message()
    request = _request(creator_ingress_message_id=message.id)
    from telegram_agent.core.admin_dashboard.services.view_models import (
        ContentProcessingView,
    )

    content = ContentProcessingView(
        job=None,
        source=None,
        download_requests=(request,),
    )
    workflows = build_workflow_collection(
        message=message,
        content=content,
        runtime=None,
        cp_available=True,
    )
    return MessageTrace(
        found=True,
        ingress_message_id=message.id,
        overall_state=OverallState.COMPLETED,
        overall_state_label="Completed",
        ingress=message,
        ingress_outbox=None,
        content_processing=content,
        agent_runtime=None,
        auth_user=None,
        timeline=(),
        failures=(),
        db_availability={
            DbName.INGRESS: DbAvailability.OK,
            DbName.CONTENT_PROCESSING: DbAvailability.OK,
            DbName.AGENT_RUNTIME: DbAvailability.OK,
            DbName.AUTH: DbAvailability.SKIPPED,
        },
        workflows=workflows,
    )


async def test_workflow_fragment_renders_ordered_status() -> None:
    trace = _trace()
    app = _app()
    response = await message_workflows_fragment(
        request=_http_request(app),
        ingress_message_id=trace.ingress_message_id,
        admin_user="admin",
        trace_service=_TraceService(trace),  # type: ignore[arg-type]
    )

    assert response.status_code == 200
    body = response.body.decode()
    assert "Video subtitles" in body
    assert "Translate transcript" in body
    assert 'data-poll-needed="true"' in body


def test_workflow_fragment_route_is_registered_and_requires_admin() -> None:
    app = _app()
    assert any(
        getattr(route, "path", None) == "/messages/{ingress_message_id}/workflows"
        for route in router.routes
    )
    with pytest.raises(HTTPException) as exc_info:
        require_admin(_http_request(app, authenticated=False))
    assert exc_info.value.status_code == 401
