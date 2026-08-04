from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from contextlib import AbstractContextManager
from datetime import timedelta
from pathlib import Path
from typing import Callable
from uuid import UUID

from telegram_agent.core.gpu_execution.common.registry import get_workload_definition
from telegram_agent.core.gpu_execution.common.results import GpuExecutionResult
from telegram_agent.core.gpu_execution.common.settings import Settings, settings
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuJob, GpuOutboxEvent
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import SyncSqlAlchemyGpuExecutionUnitOfWork
from telegram_agent.core.gpu_execution.db.uow.sync_uow_factory import sync_gpu_execution_uow_factory
from telegram_agent.core.gpu_execution.workloads.runner import (
    EXIT_CUDA_OUT_OF_MEMORY,
    EXIT_INVALID_DESCRIPTOR,
    EXIT_PERMANENT_FAILURE,
)


class SyncGpuExecutionService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyGpuExecutionUnitOfWork]],
        settings: Settings,
        worker_id: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}"
        self._lease_timeout = timedelta(seconds=settings.gpu_job_lease_seconds)

    @classmethod
    def from_settings(cls) -> "SyncGpuExecutionService":
        return cls(uow_factory=sync_gpu_execution_uow_factory, settings=settings)

    def execute(self, job_id: UUID) -> GpuExecutionResult:
        job = self._claim(job_id)
        if job is None:
            with self._uow_factory() as uow:
                resource_busy = uow.jobs.slot_is_held_by_another_job(job_id=job_id)
            return GpuExecutionResult(
                duplicate_active_delivery=not resource_busy,
                resource_busy=resource_busy,
            )

        output_path = Path(job.output_path)
        if self._valid_existing_output(job, output_path):
            with self._uow_factory() as uow:
                uow.jobs.mark_succeeded(job_id=job.id, worker_id=self._worker_id)
            return GpuExecutionResult()

        attempt_dir = (
            self._settings.gpu_shared_storage_root.expanduser().resolve()
            / ".gpu-control"
            / str(job.id)
            / f"attempt-{job.attempt_count}"
        )
        descriptor_path = attempt_dir / "descriptor.json"
        failure_path = attempt_dir / "failure.json"
        log_path = attempt_dir / "workload.log"
        temporary_output_path = output_path.with_name(
            f".{output_path.name}.{job.id}.attempt-{job.attempt_count}.part"
        )
        failure_path.unlink(missing_ok=True)
        temporary_output_path.unlink(missing_ok=True)
        self._write_descriptor(
            path=descriptor_path,
            job=job,
            temporary_output_path=temporary_output_path,
            failure_path=failure_path,
        )

        process: subprocess.Popen[bytes] | None = None
        try:
            attempt_dir.mkdir(parents=True, exist_ok=True)
            with log_path.open("ab", buffering=0) as log_file:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "telegram_agent.core.gpu_execution.workloads.runner",
                        str(descriptor_path),
                    ],
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    close_fds=True,
                    start_new_session=True,
                )
                with self._uow_factory() as uow:
                    if not uow.jobs.set_process_id(
                        job_id=job.id,
                        worker_id=self._worker_id,
                        process_id=process.pid,
                    ):
                        self._terminate_process(process)
                        return GpuExecutionResult(duplicate_active_delivery=True)
                return self._monitor(
                    job=job,
                    process=process,
                    output_path=output_path,
                    temporary_output_path=temporary_output_path,
                    failure_path=failure_path,
                )
        except (OSError, subprocess.SubprocessError) as exc:
            if process is not None:
                self._terminate_process(process)
            return self._record_retryable_failure(
                job,
                error_kind="crash",
                error_message=f"Unable to start GPU workload process: {exc}",
            )
        except BaseException:
            if process is not None:
                self._terminate_process(process)
            self._record_retryable_failure(
                job,
                error_kind="worker_lost",
                error_message="GPU executor was interrupted while workload was running",
            )
            raise
        finally:
            temporary_output_path.unlink(missing_ok=True)

    def _claim(self, job_id: UUID) -> GpuJob | None:
        with self._uow_factory() as uow:
            return uow.jobs.claim(
                job_id=job_id,
                worker_id=self._worker_id,
                lease_timeout=self._lease_timeout,
            )

    def _monitor(
        self,
        *,
        job: GpuJob,
        process: subprocess.Popen[bytes],
        output_path: Path,
        temporary_output_path: Path,
        failure_path: Path,
    ) -> GpuExecutionResult:
        started = time.monotonic()
        while True:
            return_code = process.poll()
            if return_code is not None:
                break
            if time.monotonic() - started >= job.timeout_seconds:
                self._terminate_process(process)
                return self._record_retryable_failure(
                    job,
                    error_kind="timeout",
                    error_message=(
                        f"GPU workload exceeded timeout of {job.timeout_seconds} seconds"
                    ),
                )
            with self._uow_factory() as uow:
                if uow.jobs.cancellation_requested(
                    job_id=job.id,
                    worker_id=self._worker_id,
                ):
                    self._terminate_process(process)
                    output_path.unlink(missing_ok=True)
                    temporary_output_path.unlink(missing_ok=True)
                    uow.jobs.mark_canceled(job_id=job.id, worker_id=self._worker_id)
                    return GpuExecutionResult()
                if not uow.jobs.heartbeat(
                    job_id=job.id,
                    worker_id=self._worker_id,
                    lease_timeout=self._lease_timeout,
                ):
                    self._terminate_process(process)
                    return GpuExecutionResult(duplicate_active_delivery=True)
            time.sleep(self._settings.gpu_job_heartbeat_seconds)

        if return_code == 0 and self._valid_existing_output(job, output_path):
            with self._uow_factory() as uow:
                if uow.jobs.cancellation_requested(
                    job_id=job.id,
                    worker_id=self._worker_id,
                ):
                    output_path.unlink(missing_ok=True)
                    uow.jobs.mark_canceled(job_id=job.id, worker_id=self._worker_id)
                elif not uow.jobs.mark_succeeded(
                    job_id=job.id,
                    worker_id=self._worker_id,
                ):
                    return GpuExecutionResult(duplicate_active_delivery=True)
            return GpuExecutionResult()

        failure_kind, failure_message = self._read_failure(
            failure_path,
            fallback_message=f"GPU workload process exited with code {return_code}",
        )
        if return_code in (EXIT_PERMANENT_FAILURE, EXIT_INVALID_DESCRIPTOR):
            with self._uow_factory() as uow:
                uow.jobs.mark_failed(
                    job_id=job.id,
                    worker_id=self._worker_id,
                    error_kind=failure_kind,
                    error_message=failure_message,
                )
            return GpuExecutionResult()
        if return_code == EXIT_CUDA_OUT_OF_MEMORY:
            failure_kind = "cuda_out_of_memory"
        return self._record_retryable_failure(
            job,
            error_kind=failure_kind,
            error_message=failure_message,
        )

    def _record_retryable_failure(
        self,
        job: GpuJob,
        *,
        error_kind: str,
        error_message: str,
    ) -> GpuExecutionResult:
        delay = timedelta(
            seconds=self._settings.gpu_job_retry_base_seconds
            * (2 ** max(job.attempt_count - 1, 0))
        )
        retry_scheduled = False
        with self._uow_factory() as uow:
            updated = uow.jobs.mark_retrying(
                job_id=job.id,
                worker_id=self._worker_id,
                error_kind=error_kind,
                error_message=error_message,
                retry_delay=delay,
            )
            if updated is not None and updated.status == GpuJobStatus.RETRYING:
                delivery_key = f"gpu.execute:{updated.id}:attempt:{updated.attempt_count + 1}"
                if uow.outbox_events.get_by_delivery_key(delivery_key) is None:
                    uow.outbox_events.add(
                        GpuOutboxEvent(
                            gpu_job_id=updated.id,
                            delivery_key=delivery_key,
                            available_at=updated.available_at,
                        )
                    )
                retry_scheduled = True
        return GpuExecutionResult(retry_scheduled=retry_scheduled)

    def _valid_existing_output(self, job: GpuJob, path: Path) -> bool:
        if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
            return False
        definition = get_workload_definition(job.workload_type)
        if definition is None:
            return False
        if definition.output_kind == "json":
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                return False
        return True

    @staticmethod
    def _write_descriptor(
        *,
        path: Path,
        job: GpuJob,
        temporary_output_path: Path,
        failure_path: Path,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.part")
        temporary.write_text(
            json.dumps(
                {
                    "job_id": str(job.id),
                    "workload_type": job.workload_type,
                    "input_path": job.input_path,
                    "output_path": job.output_path,
                    "temporary_output_path": str(temporary_output_path),
                    "failure_path": str(failure_path),
                    "parent_process_id": os.getpid(),
                    "parameters": job.parameters,
                }
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)

    @staticmethod
    def _read_failure(path: Path, *, fallback_message: str) -> tuple[str, str]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            kind = str(payload.get("kind") or "crash")
            message = str(payload.get("message") or fallback_message)
            return kind, message
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return "crash", fallback_message

    def _terminate_process(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + self._settings.gpu_job_cancel_grace_seconds
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return
            time.sleep(0.2)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=5)
