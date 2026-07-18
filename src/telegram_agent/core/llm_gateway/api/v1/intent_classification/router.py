from __future__ import annotations

from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Response

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.llm_gateway.api.v1.intent_classification.dependencies import (
    get_intent_classification_service,
)
from telegram_agent.core.llm_gateway.api.v1.intent_classification.schemas import (
    ErrorResponse,
    IntentClassificationHttpResponse,
    IntentClassificationRequest,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.services.generation import GenerationService

router = APIRouter(
    prefix="/intent-classification",
    tags=["intent_classification"],
    dependencies=[Depends(VerifyApiToken(settings.llm_gateway_service_token))],
)


@router.post(
    "",
    response_model=IntentClassificationHttpResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        424: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def classify_intent(
    payload: IntentClassificationRequest,
    response: Response,
    service: Annotated[
        GenerationService,
        Depends(get_intent_classification_service),
    ],
) -> IntentClassificationHttpResponse:
    request_id = str(uuid4())
    response.headers["X-Request-ID"] = request_id
    result = await service.generate(
        GenerateCommand(
            request_id=request_id,
            system_prompt=payload.system_prompt,
            user_prompt=payload.user_prompt,
        )
    )
    return IntentClassificationHttpResponse.model_validate(result, from_attributes=True)
