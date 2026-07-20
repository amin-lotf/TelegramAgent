from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.llm_gateway.api.v1.subtitle_translation.dependencies import (
    get_subtitle_translation_service,
)
from telegram_agent.core.llm_gateway.api.v1.subtitle_translation.schemas import (
    ErrorResponse,
    SubtitleTranslationHttpResponse,
    SubtitleTranslationRequest,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.services.generation import GenerationService

router = APIRouter(
    prefix="/subtitle-translation",
    tags=["subtitle_translation"],
    dependencies=[Depends(VerifyApiToken(settings.llm_gateway_service_token))],
)


@router.post(
    "",
    response_model=SubtitleTranslationHttpResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        424: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def translate_subtitle_batch(
    payload: SubtitleTranslationRequest,
    response: Response,
    service: Annotated[
        GenerationService,
        Depends(get_subtitle_translation_service),
    ],
) -> SubtitleTranslationHttpResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    result = await service.generate(
        GenerateCommand(
            request_id=request_id,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
        )
    )
    return SubtitleTranslationHttpResponse.model_validate(result, from_attributes=True)
