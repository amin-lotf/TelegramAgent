from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.llm_gateway.api.v1.glossary_extraction.dependencies import (
    get_glossary_extraction_service,
)
from telegram_agent.core.llm_gateway.api.v1.glossary_extraction.schemas import (
    ErrorResponse,
    GlossaryExtractionHttpResponse,
    GlossaryExtractionRequest,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.services.generation import GenerationService

router = APIRouter(
    prefix="/glossary-extraction",
    tags=["glossary_extraction"],
    dependencies=[Depends(VerifyApiToken(settings.llm_gateway_service_token))],
)


@router.post(
    "",
    response_model=GlossaryExtractionHttpResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        424: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def extract_glossary(
    payload: GlossaryExtractionRequest,
    response: Response,
    service: Annotated[
        GenerationService,
        Depends(get_glossary_extraction_service),
    ],
) -> GlossaryExtractionHttpResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    result = await service.generate(
        GenerateCommand(
            request_id=request_id,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
        )
    )
    return GlossaryExtractionHttpResponse.model_validate(result, from_attributes=True)
