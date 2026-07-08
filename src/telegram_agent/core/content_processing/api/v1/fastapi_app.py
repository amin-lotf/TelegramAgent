from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from telegram_agent.core.common.api.exception_handlers import register_exception_handlers
from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.content_processing.api.v1.router import api_router
from telegram_agent.core.content_processing.common.settings import settings

logger = logging.getLogger(__name__)



def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(f_app: FastAPI):
       yield


    setup_logging(settings.LOG_LEVEL)
    f_app = FastAPI(
        title="content processing API",
        description="content processing API for FatolAI Telegram Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    f_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    f_app.include_router(api_router, prefix="/api/v1")

    @f_app.get("/api",)
    @f_app.get("/api/",)
    async def root():
        return {"status": "ok", "service": "content processing", "version": "0.1.0"}

    @f_app.get("/health")
    @f_app.get("/health/")
    async def health():
        return {
            "status": "ok",
            "service": "content processing",
            "version": "0.1.0",
        }

    register_exception_handlers(f_app)
    return f_app


fastapi_app = create_app()
