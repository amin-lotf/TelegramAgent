from __future__ import annotations

from functools import lru_cache

from telegram_agent.core.llm_gateway.common.exceptions import LlmGatewayAuthenticationError
from telegram_agent.core.llm_gateway.common.schemas import IntentClassificationResponse
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.llm.openai_langchain import get_operator
from telegram_agent.core.llm_gateway.services.generation import GenerationService


@lru_cache(maxsize=1)
def _build_intent_classification_service() -> GenerationService:
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(IntentClassificationResponse)
    return GenerationService(llm=structured, provider_name="openai")


async def get_intent_classification_service() -> GenerationService:
    return _build_intent_classification_service()
