from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.gpu_workloads import (
    MADLAD_TRANSLATION_WORKLOAD,
    WHISPERX_TRANSCRIPTION_WORKLOAD,
)
from telegram_agent.core.gpu_execution.common.commands import SubmitGpuJobCommand
from telegram_agent.core.gpu_execution.common.settings import settings
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuJob, GpuOutboxEvent
from telegram_agent.core.gpu_execution.services import execution_service
from telegram_agent.core.gpu_execution.services.execution_service import SyncGpuExecutionService
from telegram_agent.core.gpu_execution.services.job_service import SyncGpuJobService


def _submit(gpu_execution_sync_uow_factory, tmp_path: Path):
    input_path = tmp_path / "input.ogg"
    input_path.write_bytes(b"audio")
    service_settings = settings.model_copy(
        update={"gpu_shared_storage_root": tmp_path}
    )
    snapshot, _ = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=service_settings,
    ).submit(
        SubmitGpuJobCommand(
            workload_type=WHISPERX_TRANSCRIPTION_WORKLOAD,
            idempotency_key="gpu-execution-test",
            input_path=str(input_path),
            output_path=str(tmp_path / "output.json"),
            parameters={"model": "large-v3"},
            timeout_seconds=60,
            max_attempts=3,
        )
    )
    return snapshot, service_settings


def test_retryable_child_failure_persists_retry_and_new_delivery(
    gpu_execution_sync_sessionmaker: sessionmaker[Session],
    gpu_execution_sync_uow_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot, service_settings = _submit(gpu_execution_sync_uow_factory, tmp_path)

    class FailedProcess:
        pid = 4321

        def __init__(self, command, **_kwargs) -> None:
            descriptor = json.loads(Path(command[-1]).read_text(encoding="utf-8"))
            Path(descriptor["failure_path"]).write_text(
                json.dumps({"kind": "cuda_out_of_memory", "message": "CUDA out of memory"}),
                encoding="utf-8",
            )

        def poll(self):
            return execution_service.EXIT_CUDA_OUT_OF_MEMORY

    monkeypatch.setattr(execution_service.subprocess, "Popen", FailedProcess)
    result = SyncGpuExecutionService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=service_settings,
        worker_id="worker-1",
    ).execute(snapshot.id)

    assert result.retry_scheduled is True
    with gpu_execution_sync_sessionmaker() as session:
        job = session.get(GpuJob, snapshot.id)
        events = list(
            session.scalars(
                select(GpuOutboxEvent)
                .where(GpuOutboxEvent.gpu_job_id == snapshot.id)
                .order_by(GpuOutboxEvent.created_at)
            )
        )
    assert job is not None
    assert job.status == GpuJobStatus.RETRYING
    assert job.attempt_count == 1
    assert job.error_kind == "cuda_out_of_memory"
    assert [event.delivery_key for event in events] == [
        f"gpu.execute:{snapshot.id}:attempt:1",
        f"gpu.execute:{snapshot.id}:attempt:2",
    ]


def test_atomic_output_from_lost_completion_is_adopted_without_child_restart(
    gpu_execution_sync_sessionmaker: sessionmaker[Session],
    gpu_execution_sync_uow_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    snapshot, service_settings = _submit(gpu_execution_sync_uow_factory, tmp_path)
    Path(snapshot.output_path).write_text('{"text": "already complete"}', encoding="utf-8")

    monkeypatch.setattr(
        execution_service.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("child must not restart for an atomic existing output")
        ),
    )
    SyncGpuExecutionService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=service_settings,
        worker_id="worker-1",
    ).execute(snapshot.id)

    with gpu_execution_sync_sessionmaker() as session:
        job = session.get(GpuJob, snapshot.id)
    assert job is not None and job.status == GpuJobStatus.SUCCEEDED


def test_madlad_child_env_sets_hub_cache_from_madlad_home(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MADLAD_HF_HOME", str(tmp_path))
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    madlad_env = execution_service._workload_child_env(MADLAD_TRANSLATION_WORKLOAD)
    whisper_env = execution_service._workload_child_env(
        WHISPERX_TRANSCRIPTION_WORKLOAD
    )
    assert madlad_env["HF_HUB_CACHE"] == str(tmp_path)
    assert madlad_env["HUGGINGFACE_HUB_CACHE"] == str(tmp_path)
    assert whisper_env.get("HF_HUB_CACHE") != str(tmp_path)
    assert whisper_env.get("MADLAD_HF_HOME") == str(tmp_path)


def test_madlad_popen_receives_hub_cache_env(
    gpu_execution_sync_uow_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MADLAD_HF_HOME", str(tmp_path / "madlad-hf-cache"))
    input_path = tmp_path / "input.json"
    input_path.write_text("{}", encoding="utf-8")
    service_settings = settings.model_copy(
        update={"gpu_shared_storage_root": tmp_path}
    )
    snapshot, _ = SyncGpuJobService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=service_settings,
    ).submit(
        SubmitGpuJobCommand(
            workload_type=MADLAD_TRANSLATION_WORKLOAD,
            idempotency_key="madlad-env-test",
            input_path=str(input_path),
            output_path=str(tmp_path / "output.json"),
            parameters={"model": "google/madlad400-3b-mt"},
            timeout_seconds=60,
            max_attempts=1,
        )
    )
    captured: dict[str, object] = {}

    class FinishedProcess:
        pid = 99

        def __init__(self, command, **kwargs) -> None:
            captured["env"] = kwargs.get("env")
            Path(snapshot.output_path).write_text("{}", encoding="utf-8")

        def poll(self):
            return 0

    monkeypatch.setattr(execution_service.subprocess, "Popen", FinishedProcess)
    monkeypatch.setattr(
        execution_service,
        "get_workload_definition",
        lambda workload_type: type(
            "Def",
            (),
            {
                "python_executable": sys.executable,
                "handler_module": "unused",
                "output_kind": "json",
            },
        )(),
    )
    SyncGpuExecutionService(
        uow_factory=gpu_execution_sync_uow_factory,
        settings=service_settings,
        worker_id="worker-1",
    ).execute(snapshot.id)

    env = captured["env"]
    assert isinstance(env, dict)
    assert env["HF_HUB_CACHE"] == str(tmp_path / "madlad-hf-cache")
    assert env["HUGGINGFACE_HUB_CACHE"] == str(tmp_path / "madlad-hf-cache")
