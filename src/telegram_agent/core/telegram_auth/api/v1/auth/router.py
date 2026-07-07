from fastapi import APIRouter, Depends
import logging

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.telegram_auth.api.v1.auth.dependencies import get_telegram_auth_service
from telegram_agent.core.telegram_auth.api.v1.auth.schemas import TelegramVerifyResponse, TelegramVerifyRequest, \
    TelegramCheckResponse, TelegramCheckRequest
from telegram_agent.core.telegram_auth.common.commands import VerifyTelegramUserCommand
from telegram_agent.core.telegram_auth.common.settings import settings
from telegram_agent.core.telegram_auth.services.user_authentication import UserAuthenticationService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram-auth",
    tags=["telegram-auth"],
    dependencies=[Depends(VerifyApiToken(settings.auth_service_token))],
)


@router.post("/verify", response_model=TelegramVerifyResponse)
async def verify_telegram_user(
    payload: TelegramVerifyRequest,
    service: UserAuthenticationService = Depends(get_telegram_auth_service),
) -> TelegramVerifyResponse:
    command = VerifyTelegramUserCommand(
        telegram_user_id=payload.telegram_user_id,
        chat_id=payload.chat_id,
        password=payload.password,
        username=payload.username,
        first_name=payload.first_name,
        last_name=payload.last_name,
        is_bot=payload.is_bot,
        language_code=payload.language_code,
    )
    verified = await service.verify_user(command)
    if not verified:

        return TelegramVerifyResponse(
            verified=False,
            message="Wrong password",
        )

    return TelegramVerifyResponse(
        verified=True,
        message="Verified successfully",
    )


@router.post("/check", response_model=TelegramCheckResponse)
async def check_telegram_user(
    payload: TelegramCheckRequest,
    service: UserAuthenticationService = Depends(get_telegram_auth_service),
) -> TelegramCheckResponse:
    verified = await service.check_user(payload.telegram_user_id)

    if not verified:
        return TelegramCheckResponse(
            verified=False,
            message="Please verify first using /verify password",
        )

    return TelegramCheckResponse(
        verified=True,
        message=None,
    )
