from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from telegram_agent.core.gpu_execution.common.commands import SubmitGpuJobCommand
from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.common.results import GpuJobSnapshot
from telegram_agent.core.gpu_execution.common.settings import Settings, settings
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuJob, GpuOutboxEvent
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import SyncSqlAlchemyGpuExecutionUnitOfWork
from telegram_agent.core.gpu_execution.db.uow.sync_uow_factory import sync_gpu_execution_uow_factory


class UnsupportedGpuWorkloadError(ValueError):
    """Raised when submission names no registered workload contract."""


class InvalidGpuJobPathError(ValueError):
    """Raised when input or output is outside durable shared storage."""


class GpuJobIdempotencyConflictError(RuntimeError):
    """Raised when one key is reused for different job content."""


class SyncGpuJobService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyGpuExecutionUnitOfWork]],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    @classmethod
    def from_settings(cls) -> "SyncGpuJobService":
        return cls(uow_factory=sync_gpu_execution_uow_factory, settings=settings)

    def submit(self, command: SubmitGpuJobCommand) -> tuple[GpuJobSnapshot, bool]:
        if get_workload_definition(command.workload_type) is None:
            raise UnsupportedGpuWorkloadError(
                f"Unsupported GPU workload type: {command.workload_type}"
            )
        input_path = self._validated_input_path(command.input_path)
        output_path = self._validated_output_path(command.output_path)
        if input_path == output_path:
            raise InvalidGpuJobPathError("GPU job output path must differ from input path")
        if command.timeout_seconds > self._settings.gpu_job_max_timeout_seconds:
            raise ValueError("GPU job timeout exceeds the configured maximum")
        if command.max_attempts > self._settings.gpu_job_max_attempts:
            raise ValueError("GPU job max_attempts exceeds the configured maximum")

        normalized = command.model_copy(
            update={"input_path": str(input_path), "output_path": str(output_path)}
        )
        try:
            with self._uow_factory() as uow:
                existing = uow.jobs.get_by_idempotency_key(normalized.idempotency_key)
                if existing is not None:
                    return self._existing_result(existing, normalized)
                job = uow.jobs.add(
                    GpuJob(
                        workload_type=normalized.workload_type,
                        status=GpuJobStatus.PENDING,
                        idempotency_key=normalized.idempotency_key,
                        input_path=normalized.input_path,
                        output_path=normalized.output_path,
                        parameters=normalized.parameters,
                        timeout_seconds=normalized.timeout_seconds,
                        max_attempts=normalized.max_attempts,
                    )
                )
                uow.outbox_events.add(
                    GpuOutboxEvent(
                        gpu_job_id=job.id,
                        delivery_key=self._delivery_key(job),
                        available_at=job.available_at,
                    )
                )
                uow.flush()
                return self._snapshot(job), True
        except IntegrityError:
            # A concurrent request may have won the unique idempotency-key race.
            with self._uow_factory() as uow:
                existing = uow.jobs.get_by_idempotency_key(normalized.idempotency_key)
                if existing is None:
                    raise
                return self._existing_result(existing, normalized)

    def get(self, job_id: UUID) -> GpuJobSnapshot | None:
        with self._uow_factory() as uow:
            job = uow.jobs.get_by_id(job_id)
            return self._snapshot(job) if job is not None else None

    def cancel(self, job_id: UUID) -> GpuJobSnapshot | None:
        with self._uow_factory() as uow:
            job = uow.jobs.request_cancellation(job_id=job_id)
            return self._snapshot(job) if job is not None else None

    def _existing_result(
        self,
        existing: GpuJob,
        command: SubmitGpuJobCommand,
    ) -> tuple[GpuJobSnapshot, bool]:
        matches = (
            existing.workload_type == command.workload_type
            and existing.input_path == command.input_path
            and existing.output_path == command.output_path
            and existing.parameters == command.parameters
            and existing.timeout_seconds == command.timeout_seconds
            and existing.max_attempts == command.max_attempts
        )
        if not matches:
            raise GpuJobIdempotencyConflictError(
                "Idempotency key is already associated with a different GPU job"
            )
        return self._snapshot(existing), False

    def _validated_input_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.is_symlink() or not path.is_file():
            raise InvalidGpuJobPathError("GPU job input path is missing or invalid")
        resolved = path.resolve()
        self._require_shared_path(resolved)
        if resolved.stat().st_size <= 0:
            raise InvalidGpuJobPathError("GPU job input file is empty")
        return resolved

    def _validated_output_path(self, raw_path: str) -> Path:
        path = Path(raw_path).expanduser()
        if path.exists() and (path.is_symlink() or not path.is_file()):
            raise InvalidGpuJobPathError("GPU job output path is invalid")
        resolved = path.resolve(strict=False)
        self._require_shared_path(resolved)
        return resolved

    def _require_shared_path(self, path: Path) -> None:
        root = self._settings.gpu_shared_storage_root.expanduser().resolve()
        if not path.is_relative_to(root):
            raise InvalidGpuJobPathError(
                f"GPU job paths must be inside shared storage root {root}"
            )

    @staticmethod
    def _delivery_key(job: GpuJob) -> str:
        return f"gpu.execute:{job.id}:attempt:{job.attempt_count + 1}"

    @staticmethod
    def _snapshot(job: GpuJob) -> GpuJobSnapshot:
        return GpuJobSnapshot(
            id=job.id,
            workload_type=job.workload_type,
            status=job.status,
            input_path=job.input_path,
            output_path=job.output_path,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            timeout_seconds=job.timeout_seconds,
            cancellation_requested_at=job.cancellation_requested_at,
            error_kind=job.error_kind,
            error_message=job.error_message,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )
