from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.llm_gateway.api.v1.message_grouping.dependencies import (
    get_message_grouping_service,
)
from telegram_agent.core.llm_gateway.api.v1.message_grouping.schemas import (
    ErrorResponse,
    MessageGroupingHttpResponse,
    MessageGroupingRequest,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.services.generation import GenerationService

router = APIRouter(
    prefix="/message-grouping",
    tags=["message_grouping"],
    dependencies=[Depends(VerifyApiToken(settings.llm_gateway_service_token))],
)


@router.post(
    "",
    response_model=MessageGroupingHttpResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        424: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def coordinate_message_grouping(
    payload: MessageGroupingRequest,
    response: Response,
    service: Annotated[
        GenerationService,
        Depends(get_message_grouping_service),
    ],
) -> MessageGroupingHttpResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    result = await service.generate(
        GenerateCommand(
            request_id=request_id,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
        )
    )
    return MessageGroupingHttpResponse.model_validate(result, from_attributes=True)
