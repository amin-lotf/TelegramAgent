import logging

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from telegram_agent.core.common.exceptions import (
    AgentRuntimeBatchConflictError,
    JobCreationError,
    SenseVoiceBackendBusyError,
    SenseVoiceBackendUnavailableError,
    TelegramAuthBadResponseError,
    TelegramAuthUnavailableError,
    TelegramUserUnauthorizedError,
    WhisperXBackendBusyError,
    WhisperXBackendUnavailableError,
)

logger = logging.getLogger(__name__)

def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc_handler(_: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )


    @app.exception_handler(ValidationError)
    async def validation_error_handler(_: Request, exc: ValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(TelegramUserUnauthorizedError)
    async def telegram_user_unauthorized_handler(_: Request, exc: TelegramUserUnauthorizedError):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": str(exc)},
        )

    @app.exception_handler(TelegramAuthUnavailableError)
    async def telegram_auth_unavailable_handler(_: Request, exc: TelegramAuthUnavailableError):
        logger.warning("Telegram auth service unavailable: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "Auth service temporarily unavailable"},
        )

    @app.exception_handler(TelegramAuthBadResponseError)
    async def telegram_auth_bad_response_handler(_: Request, exc: TelegramAuthBadResponseError):
        logger.error("Bad response from Telegram auth service: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content={"detail": "Invalid response from auth service"},
        )

    @app.exception_handler(JobCreationError)
    async def job_creation_error_handler(
            _: Request,
            exc: JobCreationError,
    ) -> JSONResponse:
        logger.error(
            "Content-processing job creation failed",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "detail": "Unable to create the processing job",
            },
        )

    @app.exception_handler(WhisperXBackendBusyError)
    async def whisperx_backend_busy_handler(_: Request, exc: WhisperXBackendBusyError) -> JSONResponse:
        logger.warning("WhisperX backend is busy: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "WhisperX backend is busy"},
        )

    @app.exception_handler(WhisperXBackendUnavailableError)
    async def whisperx_backend_unavailable_handler(_: Request, exc: WhisperXBackendUnavailableError) -> JSONResponse:
        logger.error("WhisperX backend is unavailable: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "WhisperX backend is unavailable"},
        )

    @app.exception_handler(SenseVoiceBackendBusyError)
    async def sensevoice_backend_busy_handler(
        _: Request,
        exc: SenseVoiceBackendBusyError,
    ) -> JSONResponse:
        logger.warning("SenseVoice backend is busy: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"detail": "SenseVoice backend is busy"},
        )

    @app.exception_handler(SenseVoiceBackendUnavailableError)
    async def sensevoice_backend_unavailable_handler(
        _: Request,
        exc: SenseVoiceBackendUnavailableError,
    ) -> JSONResponse:
        logger.error("SenseVoice backend is unavailable: %s", exc)

        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "SenseVoice backend is unavailable"},
        )

    @app.exception_handler(AgentRuntimeBatchConflictError)
    async def agent_runtime_batch_conflict_handler(
        _: Request,
        exc: AgentRuntimeBatchConflictError,
    ) -> JSONResponse:
        logger.warning("Agent runtime batch conflict: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": str(exc)},
        )