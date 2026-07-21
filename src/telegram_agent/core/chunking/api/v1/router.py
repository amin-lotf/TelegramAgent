from fastapi import APIRouter

from telegram_agent.core.chunking.api.v1.chunking.router import router as chunking_router

api_router = APIRouter()
api_router.include_router(chunking_router)
