from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SubmitGpuJobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workload_type: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=1, max_length=255)
    input_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    parameters: dict[str, object] = Field(default_factory=dict)
    timeout_seconds: int
    max_attempts: int
