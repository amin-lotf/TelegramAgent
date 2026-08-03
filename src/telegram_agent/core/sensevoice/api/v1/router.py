from fastapi import APIRouter

from telegram_agent.core.sensevoice.api.v1.emotions.router import router as emotions_router

api_router = APIRouter()
api_router.include_router(emotions_router)
