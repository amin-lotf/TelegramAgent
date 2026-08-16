from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.common.exceptions import (
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.telegram_ingress.api.v1.notifications.dependencies import (
    get_user_notification_service,
)
from telegram_agent.core.telegram_ingress.api.v1.notifications.schemas import (
    UserNotificationRequest,
    UserNotificationResponse,
)
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.services.async_user_notification import (
    AsyncUserNotificationService,
)

logger = logging.getLogger(__name__)

# Mounted under /telegram so it matches TELEGRAM_INGRESS_BASE_URL
# (…/api/v1/telegram) + /notifications/messages used by agent-runtime.
router = APIRouter(
    prefix="/telegram/notifications",
    tags=["notifications"],
    dependencies=[Depends(VerifyApiToken(settings.telegram_ingress_service_token))],
)


@router.post(
    "/messages",
    status_code=status.HTTP_200_OK,
    response_model=UserNotificationResponse,
)
async def send_user_notification(
    payload: UserNotificationRequest,
    service: Annotated[
        AsyncUserNotificationService,
        Depends(get_user_notification_service),
    ],
) -> UserNotificationResponse:
    """Send a progressive status/rejection/error text to the user as a reply."""
    try:
        message_id = await service.notify(
            chat_id=payload.chat_id,
            telegram_user_id=payload.telegram_user_id,
            text=payload.text,
            ingress_message_id=payload.ingress_message_id,
            reply_to_message_id=payload.reply_to_message_id,
            group_id=payload.group_id,
        )
    except TelegramDownloadError as exc:
        logger.warning(
            "Retryable failure sending user notification",
            extra={"chat_id": payload.chat_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram is temporarily unavailable",
        ) from exc
    except TelegramDownloadPermanentError as exc:
        logger.warning(
            "Permanent failure sending user notification",
            extra={"chat_id": payload.chat_id, "error": str(exc)},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram rejected the notification",
        ) from exc
    except RuntimeError as exc:
        logger.error("Notification service misconfigured: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Notification service is not configured",
        ) from exc

    return UserNotificationResponse(telegram_message_id=message_id)


# Back-compat path used by older agent-runtime clients.
@router.post(
    "/request-preparing",
    status_code=status.HTTP_200_OK,
    response_model=UserNotificationResponse,
    include_in_schema=False,
)
async def send_request_preparing_notification(
    payload: UserNotificationRequest,
    service: Annotated[
        AsyncUserNotificationService,
        Depends(get_user_notification_service),
    ],
) -> UserNotificationResponse:
    return await send_user_notification(payload, service)
