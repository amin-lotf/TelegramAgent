from __future__ import annotations

from fastapi import APIRouter

from telegram_agent.core.admin_dashboard.api.v1.messages.router import router as messages_router

api_router = APIRouter()
api_router.include_router(messages_router)
