from fastapi import APIRouter
from telegram_agent.core.whisperx.api.v1.transcriptions.router import router as transcriptions_router
api_router = APIRouter()
api_router.include_router(transcriptions_router)
