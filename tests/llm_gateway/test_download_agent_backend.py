from __future__ import annotations

import pytest

from telegram_agent.core.llm_gateway.api.v1.download_agent.dependencies import (
    _build_local_service,
    _build_openai_service,
    get_download_agent_service,
    schema_for_media_type,
)
from telegram_agent.core.llm_gateway.common.exceptions import PermanentLlmGatewayError
from telegram_agent.core.llm_gateway.common.schemas import (
    DownloadAgentAudioResponse,
    DownloadAgentDocumentResponse,
    DownloadAgentVideoResponse,
)
from telegram_agent.core.llm_gateway.common.settings import settings
from telegram_agent.core.llm_gateway.llm.gpu_structured import GpuStructuredLlm
from telegram_agent.core.llm_gateway.services.generation import GenerationService


def test_schema_for_media_type() -> None:
    assert schema_for_media_type("video") is DownloadAgentVideoResponse
    assert schema_for_media_type("audio") is DownloadAgentAudioResponse
    assert schema_for_media_type("document") is DownloadAgentDocumentResponse
    assert schema_for_media_type("other").__name__ == "DownloadAgentResponse"


def test_local_backend_builds_qwen_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "download_agent_backend", "local")
    monkeypatch.setattr(settings, "gpu_execution_service_token", "gpu-token")
    _build_local_service.cache_clear()
    captured: dict[str, object] = {}

    class _FakeGpu(GpuStructuredLlm):
        def __init__(self, *, schema):  # type: ignore[no-untyped-def]
            captured["schema"] = schema
            self._schema = schema

        async def ainvoke(self, input, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("ainvoke should not run in this test")

    monkeypatch.setattr(
        "telegram_agent.core.llm_gateway.api.v1.download_agent.dependencies.GpuStructuredLlm",
        _FakeGpu,
    )
    service = get_download_agent_service("video")
    assert isinstance(service, GenerationService)
    assert service._provider_name == "qwen"
    assert captured["schema"] is DownloadAgentVideoResponse
    _build_local_service.cache_clear()


def test_local_backend_requires_gpu_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "download_agent_backend", "local")
    monkeypatch.setattr(settings, "gpu_execution_service_token", None)
    _build_local_service.cache_clear()
    with pytest.raises(PermanentLlmGatewayError, match="GPU execution"):
        get_download_agent_service("video")
    _build_local_service.cache_clear()


def test_openai_backend_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "download_agent_backend", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    _build_openai_service.cache_clear()
    from telegram_agent.core.llm_gateway.common.exceptions import (
        LlmGatewayAuthenticationError,
    )

    with pytest.raises(LlmGatewayAuthenticationError):
        get_download_agent_service("audio")
    _build_openai_service.cache_clear()
