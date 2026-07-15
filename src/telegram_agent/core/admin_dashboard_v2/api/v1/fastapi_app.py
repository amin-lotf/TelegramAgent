from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from telegram_agent.core.admin_dashboard_v2.api.v1.router import router
from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard_v2.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_auth import TelegramAuthReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_ingress import TelegramIngressReader
from telegram_agent.core.admin_dashboard_v2.services.message_listing import MessageListingService
from telegram_agent.core.admin_dashboard_v2.services.message_trace import MessageTraceQueryService
from telegram_agent.core.common.logging import setup_logging


PACKAGE_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


def create_app(app_settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings = app_settings or Settings()
        setup_logging(settings.log_level)
        databases = ReadDatabaseManager.from_settings(settings)
        ingress = TelegramIngressReader(databases)
        content = ContentProcessingReader(databases)
        runtime = AgentRuntimeReader(databases)
        auth = TelegramAuthReader(databases)
        app.state.dashboard_settings = settings
        app.state.templates.env.filters["datetime"] = partial(
            _format_datetime,
            timezone_name=settings.display_timezone,
        )
        app.state.read_databases = databases
        app.state.message_listing_service = MessageListingService(
            ingress=ingress,
            content=content,
            runtime=runtime,
            auth=auth,
            settings=settings,
        )
        app.state.message_trace_service = MessageTraceQueryService(
            ingress=ingress,
            content=content,
            runtime=runtime,
            auth=auth,
            settings=settings,
        )
        try:
            yield
        finally:
            await databases.dispose()

    app = FastAPI(
        title="TelegramAgent Admin Dashboard v2",
        version="2.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["datetime"] = _format_datetime
    templates.env.filters["prettyjson"] = _pretty_json
    app.state.templates = templates
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(router)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
        )
        return response
    return app


def _format_datetime(value: Any, *, timezone_name: str = "UTC") -> str:
    if not isinstance(value, datetime):
        return "—"
    return value.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def _pretty_json(value: Any) -> str:
    return json.dumps(value, default=str, ensure_ascii=False, indent=2, sort_keys=True)


fastapi_app = create_app()
