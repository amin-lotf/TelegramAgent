from fastapi import APIRouter
from telegram_agent.core.telegram_ingress.api.v1.messages.router import router as telegram_router
api_router = APIRouter()
api_router.include_router(telegram_router)
