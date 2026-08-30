from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from telegram_agent.core.common.api.exception_handlers import register_exception_handlers
from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.llm_gateway.api.v1.router import api_router
from telegram_agent.core.llm_gateway.common.exceptions import (
    InvalidLlmGatewayRequestError,
    LlmGatewayAuthenticationError,
    PermanentLlmGatewayError,
    RetryableLlmGatewayError,
)
from telegram_agent.core.llm_gateway.common.settings import settings

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    setup_logging(settings.LOG_LEVEL)
    app = FastAPI(
        title="LLM gateway API",
        description="Use-case specific structured LLM generation service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router, prefix="/v1")

    @app.get("/health")
    @app.get("/health/")
    @app.get("/health/live")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "llm_gateway", "version": "0.1.0"}

    @app.get("/health/ready")
    async def readiness() -> JSONResponse:
        configured = bool(settings.llm_gateway_service_token)
        if configured and settings.download_agent_backend == "openai":
            configured = bool(settings.openai_api_key)
        return JSONResponse(
            status_code=(
                status.HTTP_200_OK
                if configured
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            content={
                "status": "ok" if configured else "not_ready",
                "service": "llm_gateway",
                "version": "0.1.0",
            },
        )

    @app.exception_handler(RetryableLlmGatewayError)
    async def retryable_error_handler(
        _: Request,
        exc: RetryableLlmGatewayError,
    ) -> JSONResponse:
        logger.warning("Retryable LLM generation failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "detail": "LLM generation is temporarily unavailable",
                "code": "generation_unavailable",
                "retryable": True,
            },
        )

    @app.exception_handler(InvalidLlmGatewayRequestError)
    async def invalid_request_handler(
        _: Request,
        exc: InvalidLlmGatewayRequestError,
    ) -> JSONResponse:
        logger.info("Invalid LLM generation request: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "detail": str(exc),
                "code": "invalid_generation_request",
                "retryable": False,
            },
        )

    @app.exception_handler(LlmGatewayAuthenticationError)
    async def authentication_handler(
        _: Request,
        exc: LlmGatewayAuthenticationError,
    ) -> JSONResponse:
        logger.error("LLM authentication failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            content={
                "detail": "LLM provider authentication failed",
                "code": "provider_authentication_failed",
                "retryable": False,
            },
        )

    @app.exception_handler(PermanentLlmGatewayError)
    async def permanent_handler(
        _: Request,
        exc: PermanentLlmGatewayError,
    ) -> JSONResponse:
        logger.error("Permanent LLM generation failure: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            content={
                "detail": "LLM provider rejected the generation",
                "code": "provider_rejected_generation",
                "retryable": False,
            },
        )

    register_exception_handlers(app)
    return app


fastapi_app = create_app()
