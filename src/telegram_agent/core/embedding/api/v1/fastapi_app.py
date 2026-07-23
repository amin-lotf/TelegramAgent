from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from telegram_agent.core.common.api.exception_handlers import register_exception_handlers
from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.embedding.api.v1.router import api_router
from telegram_agent.core.embedding.common.exceptions import (
    EmbeddingAuthenticationError,
    InvalidEmbeddingRequestError,
    PermanentEmbeddingError,
    RetryableEmbeddingError,
)
from telegram_agent.core.embedding.common.settings import settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield

    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="embedding API",
        description="Embedding API for FatolAI Telegram Agent",
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
        return {"status": "ok", "service": "embedding", "version": "0.1.0"}

    @app.get("/health")
    @app.get("/health/")
    @app.get("/health/live")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "embedding", "version": "0.1.0"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        configured = bool(
            settings.embedding_service_token and settings.openai_api_key
        )
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK
                if configured
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content={
                "status": "ok" if configured else "not_ready",
                "service": "embedding",
                "version": "0.1.0",
            },
        )

    @app.exception_handler(RetryableEmbeddingError)
    async def retryable_error_handler(
        _: Request,
        exc: RetryableEmbeddingError,
    ) -> JSONResponse:
        logger.warning("Retryable embedding failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "Embedding generation is temporarily unavailable",
                "code": "embedding_unavailable",
                "retryable": True,
            },
        )

    @app.exception_handler(InvalidEmbeddingRequestError)
    async def invalid_request_handler(
        _: Request,
        exc: InvalidEmbeddingRequestError,
    ) -> JSONResponse:
        logger.info("Invalid embedding request: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "detail": str(exc),
                "code": "invalid_embedding_request",
                "retryable": False,
            },
        )

    @app.exception_handler(EmbeddingAuthenticationError)
    async def authentication_handler(
        _: Request,
        exc: EmbeddingAuthenticationError,
    ) -> JSONResponse:
        logger.error("Embedding authentication failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            content={
                "detail": "Embedding provider authentication failed",
                "code": "provider_authentication_failed",
                "retryable": False,
            },
        )

    @app.exception_handler(PermanentEmbeddingError)
    async def permanent_handler(
        _: Request,
        exc: PermanentEmbeddingError,
    ) -> JSONResponse:
        logger.error("Permanent embedding failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            content={
                "detail": "Embedding provider rejected the request",
                "code": "provider_rejected_embedding",
                "retryable": False,
            },
        )

    register_exception_handlers(app)
    return app


fastapi_app = create_app()
