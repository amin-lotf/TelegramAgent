from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from telegram_agent.core.gpu_execution.common.results import GpuJobSnapshot
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus


class SubmitGpuJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload_type: str = Field(min_length=1, max_length=128)
    input_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    parameters: dict[str, object] = Field(default_factory=dict)
    timeout_seconds: int | None = Field(default=None, gt=0)
    max_attempts: int | None = Field(default=None, ge=1)


class GpuJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workload_type: str
    status: GpuJobStatus
    output_path: str
    attempt_count: int
    max_attempts: int
    timeout_seconds: int
    cancellation_requested_at: datetime | None
    error_kind: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    @classmethod
    def from_snapshot(cls, snapshot: GpuJobSnapshot) -> "GpuJobResponse":
        return cls.model_validate(snapshot)
