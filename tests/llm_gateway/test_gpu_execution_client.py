from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from telegram_agent.core.llm_gateway.clients.gpu_execution import GpuExecutionClient
from telegram_agent.core.llm_gateway.common.exceptions import RetryableLlmGatewayError
from telegram_agent.core.llm_gateway.common.settings import Settings


def _settings() -> Settings:
    return Settings(
        gpu_execution_base_url="http://gpu.test/api/v1",
        gpu_execution_service_token="gpu-token",
        gpu_execution_http_timeout_seconds=2,
        gpu_execution_poll_interval_seconds=0.01,
        gpu_execution_wait_timeout_seconds=1,
    )


@pytest.mark.asyncio
async def test_execute_and_wait_polls_until_success(tmp_path: Path) -> None:
    job_id = uuid4()
    output_path = tmp_path / "output.json"
    output_path.write_text('{"ok": true}', encoding="utf-8")
    calls = {"submit": 0, "get": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            calls["submit"] += 1
            assert request.headers["Idempotency-Key"] == "qwen.structured_generation.v1:abc"
            assert request.headers["Authorization"] == "Bearer gpu-token"
            return httpx.Response(
                202,
                json={
                    "id": str(job_id),
                    "workload_type": "qwen.structured_generation.v1",
                    "status": "pending",
                    "output_path": str(output_path),
                },
            )
        calls["get"] += 1
        return httpx.Response(
            200,
            json={
                "id": str(job_id),
                "workload_type": "qwen.structured_generation.v1",
                "status": "succeeded",
                "output_path": str(output_path),
            },
        )

    client = GpuExecutionClient(_settings(), transport=httpx.MockTransport(handler))
    result = await client.execute_and_wait(
        workload_type="qwen.structured_generation.v1",
        idempotency_key="qwen.structured_generation.v1:abc",
        input_path=tmp_path / "input.json",
        output_path=output_path,
        parameters={"model": "Qwen/Qwen3-4B-Instruct-2507"},
        timeout_seconds=90,
        max_attempts=2,
    )
    assert result == output_path.resolve()
    assert calls["submit"] == 1
    assert calls["get"] == 1


@pytest.mark.asyncio
async def test_failed_job_is_retryable() -> None:
    job_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            202 if request.method == "POST" else 200,
            json={
                "id": str(job_id),
                "workload_type": "qwen.structured_generation.v1",
                "status": "failed",
                "output_path": "/tmp/out.json",
                "error_kind": "workload_error",
                "error_message": "schema failed",
            },
        )

    client = GpuExecutionClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RetryableLlmGatewayError, match="schema failed"):
        await client.execute_and_wait(
            workload_type="qwen.structured_generation.v1",
            idempotency_key="key",
            input_path=Path("/tmp/in.json"),
            output_path=Path("/tmp/out.json"),
            parameters={},
            timeout_seconds=90,
            max_attempts=2,
        )


@pytest.mark.asyncio
async def test_unauthorized_gpu_request_is_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "Unauthorized"})

    client = GpuExecutionClient(_settings(), transport=httpx.MockTransport(handler))
    with pytest.raises(RetryableLlmGatewayError, match="authentication failed"):
        await client.execute_and_wait(
            workload_type="qwen.structured_generation.v1",
            idempotency_key="key",
            input_path=Path("/tmp/in.json"),
            output_path=Path("/tmp/out.json"),
            parameters={},
            timeout_seconds=90,
            max_attempts=2,
        )
