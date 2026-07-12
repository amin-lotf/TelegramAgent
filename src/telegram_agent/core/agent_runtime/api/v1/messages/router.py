from logging import getLogger
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response
from starlette import status

from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.common.api.security.token_verification import VerifyApiToken

logger = getLogger(__name__)

router = APIRouter(prefix="/agent-runtime", tags=["agent_runtime"])


@router.post(
    "/messages",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(VerifyApiToken(settings.agent_runtime_service_token))],
)
async def submit_message(

) -> dict[str, str]:
    return {"status": "accepted"}