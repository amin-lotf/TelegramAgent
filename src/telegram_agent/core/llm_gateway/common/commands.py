from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class GenerateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1, max_length=20_000)
    user_prompt: str = Field(min_length=1, max_length=100_000)
