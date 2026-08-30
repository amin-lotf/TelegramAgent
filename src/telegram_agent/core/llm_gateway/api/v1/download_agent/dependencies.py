from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from telegram_agent.core.llm_gateway.common.exceptions import (
    LlmGatewayAuthenticationError,
    PermanentLlmGatewayError,
)
from telegram_agent.core.llm_gateway.common.schemas import (
    DownloadAgentAudioResponse,
    DownloadAgentDocumentResponse,
    DownloadAgentResponse,
    DownloadAgentVideoResponse,
)
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.llm.gpu_structured import GpuStructuredLlm
from telegram_agent.core.llm_gateway.llm.openai_langchain import get_operator
from telegram_agent.core.llm_gateway.services.generation import GenerationService

_MEDIA_SCHEMAS: dict[str, type[BaseModel]] = {
    "video": DownloadAgentVideoResponse,
    "audio": DownloadAgentAudioResponse,
    "document": DownloadAgentDocumentResponse,
}


def schema_for_media_type(media_type: str) -> type[BaseModel]:
    return _MEDIA_SCHEMAS.get(media_type, DownloadAgentResponse)


def get_download_agent_service(media_type: str) -> GenerationService:
    if settings.download_agent_backend == "local":
        return _build_local_service(media_type)
    return _build_openai_service(media_type)


@lru_cache(maxsize=8)
def _build_openai_service(media_type: str) -> GenerationService:
    if settings.openai_api_key is None:
        raise LlmGatewayAuthenticationError("LLM provider is not configured")
    structured = get_operator().with_structured_output(schema_for_media_type(media_type))
    return GenerationService(llm=structured, provider_name="openai")


@lru_cache(maxsize=8)
def _build_local_service(media_type: str) -> GenerationService:
    if settings.gpu_execution_service_token is None:
        raise PermanentLlmGatewayError(
            "Local download-agent generation requires GPU execution configuration"
        )
    structured = GpuStructuredLlm(schema=schema_for_media_type(media_type))
    return GenerationService(llm=structured, provider_name="qwen")
