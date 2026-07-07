from fastapi import APIRouter, Depends, HTTPException
import logging

from sqlalchemy.sql.annotation import Annotated
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.telegram_ingress.api.v1.messages.dependencies import get_user_message_service
from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import TelegramUserRequest
from telegram_agent.core.telegram_ingress.common.commands import CreateUserMessageCommand
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
    dependencies=[Depends(VerifyApiToken(settings.AUTH_SERVICE_TOKEN))], )


@router.post("/messages", status_code=status.HTTP_202_ACCEPTED)
async def receive_telegram_message(
        payload: TelegramUserRequest,
        user_message_service: Annotated[AsyncUserMessageService, Depends(get_user_message_service)]
) -> dict[str, str]:
    command = CreateUserMessageCommand.from_request(payload)
    await user_message_service.create_user_message(command)
    return {"status": "accepted"}
