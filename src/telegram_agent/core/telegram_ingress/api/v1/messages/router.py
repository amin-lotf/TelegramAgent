from logging import getLogger
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.telegram_ingress.api.v1.messages.dependencies import (
    get_attachment_processing_result_service,
    get_cancel_all_command_service,
    get_telegram_auth_client,
    get_user_message_service,
)
from telegram_agent.core.telegram_ingress.api.v1.messages.schemas import (
    AttachmentProcessingResultRequest,
    TelegramUserRequest,
)
from telegram_agent.core.telegram_ingress.common.commands import (
    ApplyAttachmentProcessingResultCommand,
    CreateAttachmentCommand,
    CreateUserMessageCommand,
)
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.services.async_attachment_processing_result import (
    AsyncAttachmentProcessingResultService,
)
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService
from telegram_agent.core.telegram_ingress.services.async_cancel_all_command import (
    AsyncCancelAllCommandService,
)

logger = getLogger(__name__)

router = APIRouter(prefix="/telegram", tags=["telegram"])


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(VerifyApiToken(settings.auth_service_token))],
)
async def receive_telegram_message(
    payload: TelegramUserRequest,
    user_message_service: Annotated[
        AsyncUserMessageService,
        Depends(get_user_message_service),
    ],
    telegram_auth_client: Annotated[
        TelegramAuthClient,
        Depends(get_telegram_auth_client),
    ],
    cancel_all_command_service: Annotated[
        AsyncCancelAllCommandService,
        Depends(get_cancel_all_command_service),
    ],
) -> dict[str, str]:
    await telegram_auth_client.check_user(payload.telegram_user_id)
    if _is_cancel_all_command(payload):
        await cancel_all_command_service.accept(
            CreateUserMessageCommand(
                update_id=payload.update_id,
                telegram_user_id=payload.telegram_user_id,
                chat_id=payload.chat_id,
                message_id=payload.message_id,
                reply_message_id=payload.reply_to_message_id,
                text=payload.text,
            )
        )
        return {"status": "accepted"}
    attachment = None
    if payload.attachment is not None:
        attachment = CreateAttachmentCommand(
            type=payload.attachment.type,
            file_id=payload.attachment.file_id,
            file_unique_id=payload.attachment.file_unique_id,
        )
    command = CreateUserMessageCommand(
        update_id=payload.update_id,
        telegram_user_id=payload.telegram_user_id,
        chat_id=payload.chat_id,
        message_id=payload.message_id,
        reply_message_id=payload.reply_to_message_id,
        text=payload.text or payload.caption,
        attachment=attachment,
    )
    await user_message_service.create_user_message(command)
    return {"status": "accepted"}


def _is_cancel_all_command(payload: TelegramUserRequest) -> bool:
    if payload.attachment is not None or payload.text is None:
        return False
    text = payload.text.strip()
    if not text or any(character.isspace() for character in text):
        return False
    command, separator, bot_name = text.partition("@")
    if command.casefold() != "/cancel_all":
        return False
    if not separator:
        return True
    return bool(bot_name) and bot_name.replace("_", "").isalnum()


@router.post(
    "/attachments/{attachment_id}/processing-result",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(VerifyApiToken(settings.telegram_ingress_service_token))],
)
async def receive_attachment_processing_result(
    attachment_id: UUID,
    payload: AttachmentProcessingResultRequest,
    processing_result_service: Annotated[
        AsyncAttachmentProcessingResultService,
        Depends(get_attachment_processing_result_service),
    ],
) -> Response:
    result = await processing_result_service.apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=payload.ingress_message_id,
            ingress_attachment_id=attachment_id,
            status=payload.status,
            transcribed_text=payload.transcribed_text,
        )
    )
    if not result.applied:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ingress message attachment not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
