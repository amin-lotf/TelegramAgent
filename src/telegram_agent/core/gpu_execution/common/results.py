from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from telegram_agent.core.gpu_execution.common.types import GpuJobStatus


@dataclass(frozen=True)
class GpuJobSnapshot:
    id: UUID
    workload_type: str
    status: GpuJobStatus
    input_path: str
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


@dataclass(frozen=True)
class GpuExecutionResult:
    retry_scheduled: bool = False
    duplicate_active_delivery: bool = False
    resource_busy: bool = False
