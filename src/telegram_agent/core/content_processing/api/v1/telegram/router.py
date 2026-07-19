from typing import Annotated

from fastapi import APIRouter, Depends, Header
import logging

from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.content_processing.api.v1.telegram.dependencies import (
    get_telegram_auth_client,
    get_telegram_job_service,
)
from telegram_agent.core.content_processing.api.v1.telegram.schemas import (
    AcceptAudioDownloadRequest,
    AcceptDocumentDownloadRequest,
    AcceptDownloadResponse,
    AcceptVideoDownloadRequest,
    CreateContentProcessingJobRequest,
)
from telegram_agent.core.content_processing.common.commands import CreateTelegramJobCommand
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.async_telegram_job_service import (
    AsyncTelegramJobService,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
    dependencies=[Depends(VerifyApiToken(settings.content_processing_service_token))],
)


@router.post("/attachments", status_code=status.HTTP_202_ACCEPTED)
async def receive_telegram_message(
    payload: CreateContentProcessingJobRequest,
    telegram_auth_client: Annotated[TelegramAuthClient, Depends(get_telegram_auth_client)],
    telegram_job_service: Annotated[
        AsyncTelegramJobService, Depends(get_telegram_job_service)
    ],
) -> dict[str, str]:
    await telegram_auth_client.check_user(payload.telegram_user_id)
    command = CreateTelegramJobCommand.model_validate(payload.model_dump())
    await telegram_job_service.create_job(command)
    return {"status": "accepted"}


@router.post(
    "/downloads/video",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptDownloadResponse,
)
async def accept_video_download_request(
    payload: AcceptVideoDownloadRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    """Accept a video download handoff from agent-runtime (placeholder)."""
    logger.info(
        "Accepted video download handoff from agent-runtime",
        extra={
            "chat_id": payload.chat_id,
            "group_id": str(payload.group_id),
            "agent_message_id": str(payload.agent_message_id),
            "media_ingress_message_id": str(payload.media_ingress_message_id),
            "requested_subtitle_language": payload.requested_subtitle_language,
            "requested_dub_language": payload.requested_dub_language,
            "idempotency_key": idempotency_key,
        },
    )
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type="video",
    )


@router.post(
    "/downloads/audio",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptDownloadResponse,
)
async def accept_audio_download_request(
    payload: AcceptAudioDownloadRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    """Accept an audio download handoff from agent-runtime (placeholder)."""
    logger.info(
        "Accepted audio download handoff from agent-runtime",
        extra={
            "chat_id": payload.chat_id,
            "group_id": str(payload.group_id),
            "agent_message_id": str(payload.agent_message_id),
            "media_ingress_message_id": str(payload.media_ingress_message_id),
            "requested_language": payload.requested_language,
            "idempotency_key": idempotency_key,
        },
    )
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type="audio",
    )


@router.post(
    "/downloads/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptDownloadResponse,
)
async def accept_document_download_request(
    payload: AcceptDocumentDownloadRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    """Accept a document download handoff from agent-runtime (placeholder)."""
    logger.info(
        "Accepted document download handoff from agent-runtime",
        extra={
            "chat_id": payload.chat_id,
            "group_id": str(payload.group_id),
            "agent_message_id": str(payload.agent_message_id),
            "media_ingress_message_id": str(payload.media_ingress_message_id),
            "requested_format": payload.requested_format,
            "idempotency_key": idempotency_key,
        },
    )
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type="document",
    )
