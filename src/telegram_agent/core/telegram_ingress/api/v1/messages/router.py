from fastapi import APIRouter, Depends, HTTPException
import logging

from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import TelegramUserRequest
from telegram_agent.core.telegram_ingress.common.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram",
    tags=["telegram"],
    dependencies=[Depends(VerifyApiToken(settings.AUTH_SERVICE_TOKEN))], )



@router.post("/messages", status_code=status.HTTP_202_ACCEPTED)
async def receive_telegram_message(
    payload: TelegramUserRequest,
) -> dict[str, str]:
    if payload.telegram_user_id is None or payload.chat_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="telegram_user_id and chat_id are required.",
        )

    return {"status": "accepted"}