from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_agent.core.common.exceptions import (
    GpuExecutionCanceledError,
    GpuExecutionResponseError,
    GpuExecutionServiceError,
)
from telegram_agent.core.content_processing.common.settings import Settings


class GpuJobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    workload_type: str
    status: str
    output_path: str
    error_kind: str | None = None
    error_message: str | None = None


class GpuExecutionClient:
    """Transport adapter for durable GPU job submission and observation."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.gpu_execution_base_url.rstrip("/")
        self._token = settings.gpu_execution_service_token
        self._http_timeout = httpx.Timeout(
            settings.gpu_execution_http_timeout_seconds
        )
        self._poll_interval_seconds = settings.gpu_execution_poll_interval_seconds
        self._wait_timeout_seconds = settings.gpu_execution_wait_timeout_seconds

    def execute_and_wait(
        self,
        *,
        workload_type: str,
        idempotency_key: str,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
        timeout_seconds: int,
        max_attempts: int,
        heartbeat: Callable[[], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> Path:
        job = self.submit(
            workload_type=workload_type,
            idempotency_key=idempotency_key,
            input_path=input_path,
            output_path=output_path,
            parameters=parameters,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        return self.wait(
            job=job,
            expected_output_path=output_path,
            heartbeat=heartbeat,
            cancellation_requested=cancellation_requested,
        )

    def wait(
        self,
        *,
        job: GpuJobResponse,
        expected_output_path: Path,
        heartbeat: Callable[[], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> Path:
        deadline = time.monotonic() + self._wait_timeout_seconds
        while True:
            if cancellation_requested is not None and cancellation_requested():
                self.cancel(job.id)
                raise GpuExecutionCanceledError("GPU workload was canceled")
            if job.status == "succeeded":
                result_path = Path(job.output_path)
                if result_path != expected_output_path.resolve(strict=False):
                    raise GpuExecutionResponseError(
                        "GPU execution returned an unexpected output path"
                    )
                try:
                    invalid_result = (
                        result_path.is_symlink()
                        or not result_path.is_file()
                        or result_path.stat().st_size <= 0
                    )
                except OSError as exc:
                    raise GpuExecutionResponseError(
                        "GPU execution output could not be inspected"
                    ) from exc
                if invalid_result:
                    raise GpuExecutionResponseError(
                        "GPU execution succeeded without a valid output file"
                    )
                return result_path
            if job.status == "failed":
                detail = job.error_message or "GPU workload failed"
                raise GpuExecutionResponseError(detail)
            if job.status == "canceled":
                raise GpuExecutionCanceledError("GPU workload was canceled")
            if job.status not in ("pending", "running", "retrying"):
                raise GpuExecutionResponseError(
                    f"GPU execution returned unsupported status {job.status!r}"
                )
            if time.monotonic() >= deadline:
                raise GpuExecutionServiceError(
                    "Timed out while waiting for the durable GPU job to finish"
                )
            if heartbeat is not None:
                heartbeat()
            time.sleep(self._poll_interval_seconds)
            job = self.get(job.id)

    def cancel(self, job_id: UUID) -> None:
        self._request("POST", f"/jobs/{job_id}/cancel")

    def submit(
        self,
        *,
        workload_type: str,
        idempotency_key: str,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
        timeout_seconds: int,
        max_attempts: int,
    ) -> GpuJobResponse:
        payload = {
            "workload_type": workload_type,
            "input_path": str(input_path.resolve()),
            "output_path": str(output_path.resolve(strict=False)),
            "parameters": parameters,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return self._request(
            "POST",
            "/jobs",
            json=payload,
            extra_headers={"Idempotency-Key": idempotency_key},
        )

    def get(self, job_id: UUID) -> GpuJobResponse:
        return self._request("GET", f"/jobs/{job_id}")

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, object] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> GpuJobResponse:
        headers = dict(extra_headers or {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            with httpx.Client(timeout=self._http_timeout) as client:
                response = client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=json,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GpuExecutionServiceError(
                "GPU execution service is temporarily unavailable"
            ) from exc
        if response.status_code >= 500 or response.status_code in (408, 429):
            raise GpuExecutionServiceError(
                "GPU execution service is temporarily unavailable"
            )
        if response.status_code >= 400:
            raise GpuExecutionResponseError(
                f"GPU execution rejected the request with status {response.status_code}"
            )
        try:
            return GpuJobResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise GpuExecutionResponseError(
                "GPU execution returned an invalid response"
            ) from exc
