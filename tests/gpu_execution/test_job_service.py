from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.gpu_workloads import WHISPERX_TRANSCRIPTION_WORKLOAD
from telegram_agent.core.gpu_execution.common.commands import SubmitGpuJobCommand
from telegram_agent.core.gpu_execution.common.settings import settings
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuJob, GpuOutboxEvent
from telegram_agent.core.gpu_execution.services.job_service import (
    GpuJobIdempotencyConflictError,
    SyncGpuJobService,
)


def _command(input_path: Path, output_path: Path) -> SubmitGpuJobCommand:
    return SubmitGpuJobCommand(
        workload_type=WHISPERX_TRANSCRIPTION_WORKLOAD,
        idempotency_key="transcription:content-job-1",
        input_path=str(input_path),
        output_path=str(output_path),
        parameters={"model": "large-v3"},
        timeout_seconds=600,
        max_attempts=3,
    )


def test_submission_is_durable_and_idempotent(
    gpu_execution_sync_sessionmaker: sessionmaker[Session],
    gpu_execution_sync_uow_factory,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.ogg"
    input_path.write_bytes(b"audio")
    output_path = tmp_path / "results" / "transcript.json"
    service = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=settings.model_copy(
            update={"gpu_shared_storage_root": tmp_path}
        ),
    )

    first, created = service.submit(_command(input_path, output_path))
    second, duplicate_created = service.submit(_command(input_path, output_path))

    assert created is True
    assert duplicate_created is False
    assert second.id == first.id
    assert first.status == GpuJobStatus.PENDING
    with gpu_execution_sync_sessionmaker() as session:
        jobs = list(session.scalars(select(GpuJob)))
        events = list(session.scalars(select(GpuOutboxEvent)))
    assert len(jobs) == 1
    assert len(events) == 1
    assert events[0].delivery_key == f"gpu.execute:{first.id}:attempt:1"


def test_idempotency_key_rejects_changed_job(
    gpu_execution_sync_uow_factory,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.ogg"
    input_path.write_bytes(b"audio")
    service = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=settings.model_copy(update={"gpu_shared_storage_root": tmp_path}),
    )
    service.submit(_command(input_path, tmp_path / "first.json"))

    with pytest.raises(GpuJobIdempotencyConflictError):
        service.submit(_command(input_path, tmp_path / "second.json"))


def test_running_job_cancellation_is_observed_before_terminal_transition(
    gpu_execution_sync_uow_factory,
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.ogg"
    input_path.write_bytes(b"audio")
    service = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=settings.model_copy(update={"gpu_shared_storage_root": tmp_path}),
    )
    snapshot, _ = service.submit(_command(input_path, tmp_path / "output.json"))
    with gpu_execution_sync_uow_factory() as uow:
        claimed = uow.jobs.claim(
            job_id=snapshot.id,
            worker_id="worker-1",
            lease_timeout=timedelta(seconds=60),
        )
        assert claimed is not None

    cancel_snapshot = service.cancel(snapshot.id)
    assert cancel_snapshot is not None
    assert cancel_snapshot.status == GpuJobStatus.RUNNING
    assert cancel_snapshot.cancellation_requested_at is not None

    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.cancellation_requested(
            job_id=snapshot.id,
            worker_id="worker-1",
        )
        assert uow.jobs.mark_canceled(
            job_id=snapshot.id,
            worker_id="worker-1",
        )
    terminal = service.get(snapshot.id)
    assert terminal is not None and terminal.status == GpuJobStatus.CANCELED


def test_database_slot_prevents_two_gpu_jobs_from_running(
    gpu_execution_sync_uow_factory,
    tmp_path: Path,
) -> None:
    first_input = tmp_path / "first.ogg"
    second_input = tmp_path / "second.ogg"
    first_input.write_bytes(b"first")
    second_input.write_bytes(b"second")
    service = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=settings.model_copy(update={"gpu_shared_storage_root": tmp_path}),
    )
    first, _ = service.submit(_command(first_input, tmp_path / "first.json"))
    second_command = _command(second_input, tmp_path / "second.json").model_copy(
        update={"idempotency_key": "transcription:content-job-2"}
    )
    second, _ = service.submit(second_command)

    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.claim(
            job_id=first.id,
            worker_id="worker-1",
            lease_timeout=timedelta(seconds=60),
        ) is not None
    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.heartbeat(
            job_id=first.id,
            worker_id="worker-1",
            lease_timeout=timedelta(seconds=60),
        )
    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.claim(
            job_id=second.id,
            worker_id="worker-2",
            lease_timeout=timedelta(seconds=60),
        ) is None
        assert uow.jobs.slot_is_held_by_another_job(job_id=second.id)
    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.mark_succeeded(job_id=first.id, worker_id="worker-1")
    with gpu_execution_sync_uow_factory() as uow:
        assert uow.jobs.claim(
            job_id=second.id,
            worker_id="worker-2",
            lease_timeout=timedelta(seconds=60),
        ) is not None
