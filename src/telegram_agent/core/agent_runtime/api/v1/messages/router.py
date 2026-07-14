from typing import Annotated

from fastapi import APIRouter, Depends, Header
from starlette import status

from telegram_agent.core.agent_runtime.api.v1.messages.dependencies import (
    get_message_batch_ingestion_service,
)
from telegram_agent.core.agent_runtime.api.v1.messages.schemas import (
    RuntimeMessageBatchRequest,
)
from telegram_agent.core.agent_runtime.common.commands import (
    IngestAttachmentCommand,
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent-runtime", tags=["agent_runtime"])


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(VerifyApiToken(settings.agent_runtime_service_token))],
)
async def submit_message_batch(
    payload: RuntimeMessageBatchRequest,
    idempotency_key: Annotated[
        str,
        Header(alias="Idempotency-Key", min_length=1),
    ],
    ingestion_service: Annotated[
        AsyncMessageBatchIngestionService,
        Depends(get_message_batch_ingestion_service),
    ],
) -> dict[str, str]:
    messages = tuple(
        IngestMessageCommand(
            ingress_message_id=message.ingress_message_id,
            telegram_user_id=message.telegram_user_id,
            message_id=message.message_id,
            reply_message_id=message.reply_message_id,
            text=message.text,
            attachment=(
                IngestAttachmentCommand(
                    ingress_attachment_id=message.attachment.ingress_attachment_id,
                    type=message.attachment.type,
                    status=message.attachment.status,
                    file_id=message.attachment.file_id,
                    file_unique_id=message.attachment.file_unique_id,
                )
                if message.attachment is not None
                else None
            ),
        )
        for message in payload.messages
    )
    command = IngestMessageBatchCommand(
        batch_id=payload.batch_id,
        chat_id=payload.chat_id,
        idempotency_key=idempotency_key,
        messages=messages,
    )
    result = await ingestion_service.ingest(command)
    logger.info(
        "Accepted runtime message batch",
        extra={
            "batch_id": str(result.batch_id),
            "chat_id": result.chat_id,
            "batch_created": result.created,
            "message_count": result.message_count,
        },
    )
    return {"status": "accepted"}
