from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import BaseModel

from telegram_agent.core.common.gpu_workloads import QWEN_STRUCTURED_GENERATION_WORKLOAD
from telegram_agent.core.llm_gateway.common.exceptions import RetryableLlmGatewayError
from telegram_agent.core.llm_gateway.common.schemas import DownloadAgentVideoResponse
from telegram_agent.core.llm_gateway.common.settings import Settings
from telegram_agent.core.llm_gateway.llm.gpu_structured import GpuStructuredLlm


class _FakeGpuClient:
    def __init__(self, result: dict[str, object] | None = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def execute_and_wait(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        output_path = Path(kwargs["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        assert self.result is not None
        output_path.write_text(json.dumps(self.result), encoding="utf-8")
        return output_path


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        gpu_execution_service_token="gpu-token",
        gpu_shared_storage_root=tmp_path,
        download_agent_local_model="Qwen/Qwen3-4B-Instruct-2507",
        download_agent_local_max_validation_attempts=3,
        download_agent_local_max_new_tokens=128,
        download_agent_local_job_timeout_seconds=90,
        download_agent_local_job_max_attempts=2,
        reply_temperature=0.2,
    )


@pytest.mark.asyncio
async def test_writes_schema_and_validates_gpu_result(tmp_path: Path) -> None:
    gpu = _FakeGpuClient(
        result={
            "output": {
                "is_download_request": True,
                "requested_subtitle_language": "en",
                "requested_dub_language": None,
                "assistant_text": "Preparing the video.",
            },
            "model": "Qwen/Qwen3-4B-Instruct-2507",
            "attempts": 1,
            "usage": {"input_tokens": 8, "output_tokens": 4, "total_tokens": 12},
        }
    )
    llm = GpuStructuredLlm(
        schema=DownloadAgentVideoResponse,
        gpu_client=gpu,  # type: ignore[arg-type]
        settings=_settings(tmp_path),
    )

    result = await llm.ainvoke(
        [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "english subtitles"},
        ],
        request_id="download-agent:abc",
    )

    assert isinstance(result.output, BaseModel)
    assert result.output.is_download_request is True
    assert result.model == "Qwen/Qwen3-4B-Instruct-2507"
    assert result.usage.total_tokens == 12
    assert len(gpu.calls) == 1
    call = gpu.calls[0]
    assert call["workload_type"] == QWEN_STRUCTURED_GENERATION_WORKLOAD
    assert call["idempotency_key"] == (
        f"{QWEN_STRUCTURED_GENERATION_WORKLOAD}:download-agent:abc"
    )
    input_path = Path(call["input_path"])
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    assert payload["system_prompt"] == "system"
    assert payload["user_prompt"] == "english subtitles"
    assert payload["json_schema"]["title"] == "DownloadAgentVideoResponse"


@pytest.mark.asyncio
async def test_invalid_gpu_output_is_retryable(tmp_path: Path) -> None:
    gpu = _FakeGpuClient(result={"output": {"is_download_request": True}})
    llm = GpuStructuredLlm(
        schema=DownloadAgentVideoResponse,
        gpu_client=gpu,  # type: ignore[arg-type]
        settings=_settings(tmp_path),
    )
    with pytest.raises(RetryableLlmGatewayError):
        await llm.ainvoke(
            [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ],
            request_id=str(uuid4()),
        )
