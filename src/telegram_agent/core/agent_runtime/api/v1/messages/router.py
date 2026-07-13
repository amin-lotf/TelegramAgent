from typing import Annotated

from fastapi import APIRouter, Depends, Header
from starlette import status

from telegram_agent.core.agent_runtime.api.v1.messages.schemas import (
    RuntimeMessageBatchRequest,
)
from telegram_agent.core.agent_runtime.common.settings import settings
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
) -> dict[str, str]:
    logger.info("Received message batch")
    logger.debug(f"Payload: {payload}")
    logger.debug(f"Idempotency key: {idempotency_key}")
    del payload, idempotency_key
    return {"status": "accepted"}
