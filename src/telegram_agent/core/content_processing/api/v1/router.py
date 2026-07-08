from fastapi import APIRouter
from telegram_agent.core.content_processing.api.v1.telegram.router import router as telegram_router
api_router = APIRouter()
api_router.include_router(telegram_router)
