from fastapi import APIRouter
from telegram_agent.core.agent_runtime.api.v1.messages.router import router as messages_router
api_router = APIRouter()
api_router.include_router(messages_router)
