from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class LLMTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class LLMGenerateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    output: Any
    model: str
    provider_request_id: str | None = None
    usage: LLMTokenUsage


class GenerateResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    output: dict[str, Any]
    provider: str
    model: str
    provider_request_id: str | None = None
    usage: LLMTokenUsage
