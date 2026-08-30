"""Async transport adapter for durable GPU job submission and observation."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from telegram_agent.core.llm_gateway.common.exceptions import (
    InvalidLlmGatewayRequestError,
    PermanentLlmGatewayError,
    RetryableLlmGatewayError,
)
from telegram_agent.core.llm_gateway.common.settings import Settings


class GpuJobResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    workload_type: str
    status: str
    output_path: str
    error_kind: str | None = None
    error_message: str | None = None


class GpuExecutionClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = settings.gpu_execution_base_url.rstrip("/")
        self._token = settings.gpu_execution_service_token
        self._http_timeout = httpx.Timeout(settings.gpu_execution_http_timeout_seconds)
        self._poll_interval_seconds = settings.gpu_execution_poll_interval_seconds
        self._wait_timeout_seconds = settings.gpu_execution_wait_timeout_seconds
        self._transport = transport

    async def execute_and_wait(
        self,
        *,
        workload_type: str,
        idempotency_key: str,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
        timeout_seconds: int,
        max_attempts: int,
    ) -> Path:
        job = await self.submit(
            workload_type=workload_type,
            idempotency_key=idempotency_key,
            input_path=input_path,
            output_path=output_path,
            parameters=parameters,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        return await self.wait(job=job, expected_output_path=output_path)

    async def wait(self, *, job: GpuJobResponse, expected_output_path: Path) -> Path:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._wait_timeout_seconds
        while True:
            if job.status == "succeeded":
                result_path = Path(job.output_path)
                if result_path != expected_output_path.resolve(strict=False):
                    raise PermanentLlmGatewayError(
                        "GPU execution returned an unexpected output path"
                    )
                try:
                    invalid_result = (
                        result_path.is_symlink()
                        or not result_path.is_file()
                        or result_path.stat().st_size <= 0
                    )
                except OSError as exc:
                    raise RetryableLlmGatewayError(
                        "GPU execution output could not be inspected"
                    ) from exc
                if invalid_result:
                    raise RetryableLlmGatewayError(
                        "GPU execution succeeded without a valid output file"
                    )
                return result_path
            if job.status == "failed":
                detail = job.error_message or "GPU workload failed"
                if job.error_kind == "invalid_input":
                    raise InvalidLlmGatewayRequestError(detail)
                raise RetryableLlmGatewayError(detail)
            if job.status == "canceled":
                raise PermanentLlmGatewayError("GPU workload was canceled")
            if job.status not in ("pending", "running", "retrying"):
                raise PermanentLlmGatewayError(
                    f"GPU execution returned unsupported status {job.status!r}"
                )
            if loop.time() >= deadline:
                raise RetryableLlmGatewayError(
                    "Timed out while waiting for the durable GPU job to finish"
                )
            await asyncio.sleep(self._poll_interval_seconds)
            job = await self.get(job.id)

    async def submit(
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
        payload: dict[str, object] = {
            "workload_type": workload_type,
            "input_path": str(input_path.resolve()),
            "output_path": str(output_path.resolve(strict=False)),
            "parameters": parameters,
            "timeout_seconds": timeout_seconds,
            "max_attempts": max_attempts,
        }
        return await self._request(
            "POST",
            "/jobs",
            json=payload,
            extra_headers={"Idempotency-Key": idempotency_key},
        )

    async def get(self, job_id: UUID) -> GpuJobResponse:
        return await self._request("GET", f"/jobs/{job_id}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Mapping[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> GpuJobResponse:
        headers = dict(extra_headers or {})
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        try:
            async with httpx.AsyncClient(
                timeout=self._http_timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=headers,
                    json=dict(json) if json is not None else None,
                )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableLlmGatewayError(
                "GPU execution service is temporarily unavailable"
            ) from exc
        if response.status_code in {401, 403}:
            raise RetryableLlmGatewayError(
                "GPU execution authentication failed"
            )
        if response.status_code >= 500 or response.status_code in {408, 429}:
            raise RetryableLlmGatewayError(
                "GPU execution service is temporarily unavailable"
            )
        if response.status_code == 409:
            raise PermanentLlmGatewayError(
                "GPU execution rejected a conflicting idempotency key"
            )
        if response.status_code in {400, 422}:
            raise InvalidLlmGatewayRequestError(
                "GPU execution rejected the structured generation request"
            )
        if response.status_code >= 400:
            raise PermanentLlmGatewayError(
                f"GPU execution rejected the request with status {response.status_code}"
            )
        try:
            return GpuJobResponse.model_validate(response.json())
        except (ValueError, ValidationError) as exc:
            raise RetryableLlmGatewayError(
                "GPU execution returned an invalid response"
            ) from exc
