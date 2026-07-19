from __future__ import annotations

from functools import lru_cache

from telegram_agent.core.llm_gateway.common.exceptions import LlmGatewayAuthenticationError
from telegram_agent.core.llm_gateway.common.schemas import (
    DownloadAgentAudioResponse,
    DownloadAgentDocumentResponse,
    DownloadAgentResponse,
    DownloadAgentVideoResponse,
)
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.llm.openai_langchain import get_operator
from telegram_agent.core.llm_gateway.services.generation import GenerationService


@lru_cache(maxsize=1)
def _build_video_service() -> GenerationService:
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(DownloadAgentVideoResponse)
    return GenerationService(llm=structured, provider_name="openai")


@lru_cache(maxsize=1)
def _build_audio_service() -> GenerationService:
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(DownloadAgentAudioResponse)
    return GenerationService(llm=structured, provider_name="openai")


@lru_cache(maxsize=1)
def _build_document_service() -> GenerationService:
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(DownloadAgentDocumentResponse)
    return GenerationService(llm=structured, provider_name="openai")


def get_download_agent_service(media_type: str) -> GenerationService:
    if media_type == "video":
        return _build_video_service()
    if media_type == "audio":
        return _build_audio_service()
    if media_type == "document":
        return _build_document_service()
    # Fallback keeps the generic envelope available for unexpected values.
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(DownloadAgentResponse)
    return GenerationService(llm=structured, provider_name="openai")
