from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.llm_gateway.api.v1.download_agent.dependencies import (
    get_download_agent_service,
)
from telegram_agent.core.llm_gateway.api.v1.download_agent.schemas import (
    DownloadAgentHttpResponse,
    DownloadAgentRequest,
    ErrorResponse,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.settings import settings

router = APIRouter(
    prefix="/download-agent",
    tags=["download_agent"],
    dependencies=[Depends(VerifyApiToken(settings.llm_gateway_service_token))],
)


@router.post(
    "",
    response_model=DownloadAgentHttpResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        424: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def extract_download_request(
    payload: DownloadAgentRequest,
    response: Response,
) -> DownloadAgentHttpResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    service = get_download_agent_service(payload.media_type)
    result = await service.generate(
        GenerateCommand(
            request_id=request_id,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
        )
    )
    return DownloadAgentHttpResponse.model_validate(result, from_attributes=True)
