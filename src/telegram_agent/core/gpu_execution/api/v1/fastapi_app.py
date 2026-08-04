from __future__ import annotations

from fastapi import FastAPI

from telegram_agent.core.common.api.exception_handlers import register_exception_handlers
from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.gpu_execution.api.v1.router import api_router
from telegram_agent.core.gpu_execution.common.settings import settings


def create_app() -> FastAPI:
    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="GPU execution API",
        description="Durable single-GPU workload scheduler for FatolAI Telegram Agent",
        version="0.1.0",
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/health")
    @app.get("/health/")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "gpu execution", "version": "0.1.0"}

    register_exception_handlers(app)
    return app


fastapi_app = create_app()
