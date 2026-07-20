from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from telegram_agent.core.llm_gateway.common.results import LLMTokenUsage


class GlossaryExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_prompt: str = Field(min_length=1, max_length=200_000)


class GlossaryExtractionHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    output: Any
    provider: str
    model: str
    provider_request_id: str | None = None
    usage: LLMTokenUsage


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str
    code: str
    retryable: bool
