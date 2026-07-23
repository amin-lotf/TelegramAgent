from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from telegram_agent.core.chunking.api.v1.router import api_router
from telegram_agent.core.chunking.common.settings import settings
from telegram_agent.core.common.api.exception_handlers import register_exception_handlers
from telegram_agent.core.common.logging import setup_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield

    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="chunking API",
        description="Chunking API for FatolAI Telegram Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/api")
    @app.get("/api/")
    async def root() -> dict[str, str]:
        return {"status": "ok", "service": "chunking", "version": "0.1.0"}

    @app.get("/health")
    @app.get("/health/")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "chunking", "version": "0.1.0"}

    register_exception_handlers(app)
    return app


fastapi_app = create_app()
