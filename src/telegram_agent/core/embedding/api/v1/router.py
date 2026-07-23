from fastapi import APIRouter

from telegram_agent.core.embedding.api.v1.embeddings.router import router as embeddings_router

api_router = APIRouter()
api_router.include_router(embeddings_router)
