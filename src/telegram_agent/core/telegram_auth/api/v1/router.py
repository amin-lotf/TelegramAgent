from fastapi import APIRouter
from telegram_agent.core.telegram_auth.api.v1.auth.router import router as auth_router

api_router = APIRouter()
api_router.include_router(auth_router)
