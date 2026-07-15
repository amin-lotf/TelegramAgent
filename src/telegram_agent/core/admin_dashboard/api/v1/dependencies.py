"""FastAPI dependencies for the admin dashboard."""
from __future__ import annotations

from fastapi import Request

from telegram_agent.core.admin_dashboard.common.settings import Settings, settings
from telegram_agent.core.admin_dashboard.db.engines import DashboardDatabases
from telegram_agent.core.admin_dashboard.services.message_list import MessageListService
from telegram_agent.core.admin_dashboard.services.message_trace import MessageTraceService


def get_settings() -> Settings:
    return settings


def get_databases(request: Request) -> DashboardDatabases:
    databases = getattr(request.app.state, "databases", None)
    if databases is None:
        raise RuntimeError("Dashboard databases are not initialized")
    return databases


def get_message_list_service(request: Request) -> MessageListService:
    return MessageListService(get_databases(request), get_settings())


def get_message_trace_service(request: Request) -> MessageTraceService:
    return MessageTraceService(get_databases(request), get_settings())
