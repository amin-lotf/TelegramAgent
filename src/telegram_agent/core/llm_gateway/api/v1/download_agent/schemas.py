from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from telegram_agent.core.llm_gateway.common.results import LLMTokenUsage


class DownloadAgentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_prompt: str = Field(min_length=1, max_length=100_000)
    media_type: Literal["video", "audio", "document"]
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9:._-]+$",
    )


class DownloadAgentHttpResponse(BaseModel):
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
