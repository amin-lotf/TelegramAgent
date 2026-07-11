from typing import Annotated

from fastapi import APIRouter, Depends
import logging

from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.content_processing.api.v1.telegram.dependencies import get_telegram_auth_client, \
    get_telegram_job_service
from telegram_agent.core.content_processing.api.v1.telegram.schemas import CreateContentProcessingJobRequest
from telegram_agent.core.content_processing.common.commands import CreateTelegramJobCommand
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.async_telegram_job_service import AsyncTelegramJobService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
    dependencies=[Depends(VerifyApiToken(settings.content_processing_service_token))], )


@router.post("/attachments", status_code=status.HTTP_202_ACCEPTED)
async def receive_telegram_message(
        payload: CreateContentProcessingJobRequest,
        telegram_auth_client:Annotated[TelegramAuthClient,Depends(get_telegram_auth_client)],
        telegram_job_service:Annotated[AsyncTelegramJobService,Depends(get_telegram_job_service)]
) -> dict[str, str]:
    await telegram_auth_client.check_user(payload.telegram_user_id)
    command = CreateTelegramJobCommand.model_validate(payload.model_dump())
    job_result= await telegram_job_service.create_job(command)
    return {"status": "accepted"}
