from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
import logging

from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.content_processing.api.v1.telegram.dependencies import (
    get_download_request_service,
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
from telegram_agent.core.content_processing.common.commands import (
    CreateDownloadRequestCommand,
    CreateTelegramJobCommand,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import DownloadMediaType
from telegram_agent.core.content_processing.services.async_download_request_service import (
    AsyncDownloadRequestService,
)
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
    telegram_auth_client: Annotated[TelegramAuthClient, Depends(get_telegram_auth_client)],
    download_request_service: Annotated[
        AsyncDownloadRequestService, Depends(get_download_request_service)
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    key = _require_idempotency_key(idempotency_key)
    await telegram_auth_client.check_user(payload.telegram_user_id)
    command = CreateDownloadRequestCommand(
        chat_id=payload.chat_id,
        telegram_user_id=payload.telegram_user_id,
        group_id=payload.group_id,
        agent_message_id=payload.agent_message_id,
        media_ingress_message_id=payload.media_ingress_message_id,
        media_type=DownloadMediaType.VIDEO.value,
        assistant_text=payload.assistant_text,
        requested_subtitle_language=payload.requested_subtitle_language,
        requested_dub_language=payload.requested_dub_language,
        idempotency_key=key,
    )
    await download_request_service.create_download_request(command)
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type=DownloadMediaType.VIDEO.value,
    )


@router.post(
    "/downloads/audio",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptDownloadResponse,
)
async def accept_audio_download_request(
    payload: AcceptAudioDownloadRequest,
    telegram_auth_client: Annotated[TelegramAuthClient, Depends(get_telegram_auth_client)],
    download_request_service: Annotated[
        AsyncDownloadRequestService, Depends(get_download_request_service)
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    key = _require_idempotency_key(idempotency_key)
    await telegram_auth_client.check_user(payload.telegram_user_id)
    command = CreateDownloadRequestCommand(
        chat_id=payload.chat_id,
        telegram_user_id=payload.telegram_user_id,
        group_id=payload.group_id,
        agent_message_id=payload.agent_message_id,
        media_ingress_message_id=payload.media_ingress_message_id,
        media_type=DownloadMediaType.AUDIO.value,
        assistant_text=payload.assistant_text,
        requested_language=payload.requested_language,
        idempotency_key=key,
    )
    await download_request_service.create_download_request(command)
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type=DownloadMediaType.AUDIO.value,
    )


@router.post(
    "/downloads/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptDownloadResponse,
)
async def accept_document_download_request(
    payload: AcceptDocumentDownloadRequest,
    telegram_auth_client: Annotated[TelegramAuthClient, Depends(get_telegram_auth_client)],
    download_request_service: Annotated[
        AsyncDownloadRequestService, Depends(get_download_request_service)
    ],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AcceptDownloadResponse:
    key = _require_idempotency_key(idempotency_key)
    await telegram_auth_client.check_user(payload.telegram_user_id)
    command = CreateDownloadRequestCommand(
        chat_id=payload.chat_id,
        telegram_user_id=payload.telegram_user_id,
        group_id=payload.group_id,
        agent_message_id=payload.agent_message_id,
        media_ingress_message_id=payload.media_ingress_message_id,
        media_type=DownloadMediaType.DOCUMENT.value,
        assistant_text=payload.assistant_text,
        requested_format=payload.requested_format,
        idempotency_key=key,
    )
    await download_request_service.create_download_request(command)
    return AcceptDownloadResponse(
        status="accepted",
        accepted=True,
        media_type=DownloadMediaType.DOCUMENT.value,
    )


def _require_idempotency_key(idempotency_key: str | None) -> str:
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    return idempotency_key.strip()
