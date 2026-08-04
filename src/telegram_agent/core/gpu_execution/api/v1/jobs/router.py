from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.gpu_execution.api.v1.jobs.dependencies import get_gpu_job_service
from telegram_agent.core.gpu_execution.api.v1.jobs.schemas import GpuJobResponse, SubmitGpuJobRequest
from telegram_agent.core.gpu_execution.common.commands import SubmitGpuJobCommand
from telegram_agent.core.gpu_execution.common.settings import settings
from telegram_agent.core.gpu_execution.services.job_service import (
    GpuJobIdempotencyConflictError,
    InvalidGpuJobPathError,
    SyncGpuJobService,
    UnsupportedGpuWorkloadError,
)


router = APIRouter(
    prefix="/jobs",
    tags=["gpu-jobs"],
    dependencies=[Depends(VerifyApiToken(settings.gpu_execution_service_token))],
)


@router.post("", response_model=GpuJobResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_gpu_job(
    payload: SubmitGpuJobRequest,
    service: Annotated[SyncGpuJobService, Depends(get_gpu_job_service)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> GpuJobResponse:
    if idempotency_key is None or not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required",
        )
    command = SubmitGpuJobCommand(
        workload_type=payload.workload_type,
        idempotency_key=idempotency_key.strip(),
        input_path=payload.input_path,
        output_path=payload.output_path,
        parameters=payload.parameters,
        timeout_seconds=(
            payload.timeout_seconds or settings.gpu_job_default_timeout_seconds
        ),
        max_attempts=(payload.max_attempts or settings.gpu_job_default_max_attempts),
    )
    try:
        snapshot, _created = service.submit(command)
    except GpuJobIdempotencyConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except UnsupportedGpuWorkloadError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (InvalidGpuJobPathError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return GpuJobResponse.from_snapshot(snapshot)


@router.get("/{job_id}", response_model=GpuJobResponse)
def get_gpu_job(
    job_id: UUID,
    service: Annotated[SyncGpuJobService, Depends(get_gpu_job_service)],
) -> GpuJobResponse:
    snapshot = service.get(job_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GPU job not found")
    return GpuJobResponse.from_snapshot(snapshot)


@router.post("/{job_id}/cancel", response_model=GpuJobResponse, status_code=status.HTTP_202_ACCEPTED)
def cancel_gpu_job(
    job_id: UUID,
    service: Annotated[SyncGpuJobService, Depends(get_gpu_job_service)],
) -> GpuJobResponse:
    snapshot = service.cancel(job_id)
    if snapshot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="GPU job not found")
    return GpuJobResponse.from_snapshot(snapshot)
