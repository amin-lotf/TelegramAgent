from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from telegram_agent.core.llm_gateway.api.v1.fastapi_app import create_app
from telegram_agent.core.llm_gateway.api.v1.glossary_extraction.dependencies import (
    get_glossary_extraction_service,
)
from telegram_agent.core.llm_gateway.api.v1.message_grouping.dependencies import (
    get_message_grouping_service,
)
from telegram_agent.core.llm_gateway.api.v1.subtitle_translation.dependencies import (
    get_subtitle_translation_service,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.results import GenerateResult, LLMTokenUsage
from telegram_agent.core.llm_gateway.common.settings import settings
from tests.support.fastapi import set_expected_api_token


class StubGenerationService:
    def __init__(self) -> None:
        self.commands: list[GenerateCommand] = []

    async def generate(self, command: GenerateCommand) -> GenerateResult:
        self.commands.append(command)
        return GenerateResult(
            request_id=command.request_id,
            output={"kind": "new", "group_number": None},
            provider="stub",
            model="stub-model",
            provider_request_id="provider-request",
            usage=LLMTokenUsage(
                input_tokens=5,
                output_tokens=3,
                total_tokens=8,
            ),
        )


def _payload() -> dict[str, Any]:
    return {
        "system_prompt": "system",
        "user_prompt": "user",
    }


@pytest.mark.asyncio
async def test_message_grouping_requires_service_authentication() -> None:
    app = create_app()
    set_expected_api_token(app, "gateway-token")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/v1/message-grouping", json=_payload())

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_message_grouping_returns_structured_output_and_request_id() -> None:
    app = create_app()
    set_expected_api_token(app, "gateway-token")
    service = StubGenerationService()

    async def override_service() -> StubGenerationService:
        return service

    app.dependency_overrides[get_message_grouping_service] = override_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/message-grouping",
            headers={"Authorization": "Bearer gateway-token"},
            json=_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["output"] == {"kind": "new", "group_number": None}
    assert body["provider"] == "stub"
    assert body["model"] == "stub-model"
    assert body["provider_request_id"] == "provider-request"
    assert body["usage"]["total_tokens"] == 8
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert service.commands[0].system_prompt == "system"
    assert service.commands[0].user_prompt == "user"


@pytest.mark.asyncio
async def test_glossary_extraction_returns_structured_output() -> None:
    app = create_app()
    set_expected_api_token(app, "gateway-token")
    service = StubGenerationService()
    service_output = {
        "entries": [
            {
                "source_term": "Alice",
                "preferred_translation": "آلیس",
                "category": "person",
                "expansion": None,
                "notes": None,
            }
        ],
        "tone_guidance": "Spoken style",
    }

    class GlossaryStub(StubGenerationService):
        async def generate(self, command: GenerateCommand) -> GenerateResult:
            self.commands.append(command)
            return GenerateResult(
                request_id=command.request_id,
                output=service_output,
                provider="stub",
                model="stub-model",
                provider_request_id="provider-request",
                usage=LLMTokenUsage(input_tokens=5, output_tokens=3, total_tokens=8),
            )

    glossary_service = GlossaryStub()

    async def override_service() -> GlossaryStub:
        return glossary_service

    app.dependency_overrides[get_glossary_extraction_service] = override_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/glossary-extraction",
            headers={"Authorization": "Bearer gateway-token"},
            json=_payload(),
        )

    assert response.status_code == 200
    assert response.json()["output"] == service_output


@pytest.mark.asyncio
async def test_subtitle_translation_returns_structured_output() -> None:
    app = create_app()
    set_expected_api_token(app, "gateway-token")
    service_output = {
        "translations": [
            {"segment_index": 0, "text": "سلام"},
        ]
    }

    class TranslateStub(StubGenerationService):
        async def generate(self, command: GenerateCommand) -> GenerateResult:
            self.commands.append(command)
            return GenerateResult(
                request_id=command.request_id,
                output=service_output,
                provider="stub",
                model="stub-model",
                provider_request_id="provider-request",
                usage=LLMTokenUsage(input_tokens=5, output_tokens=3, total_tokens=8),
            )

    translate_service = TranslateStub()

    async def override_service() -> TranslateStub:
        return translate_service

    app.dependency_overrides[get_subtitle_translation_service] = override_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/subtitle-translation",
            headers={"Authorization": "Bearer gateway-token"},
            json=_payload(),
        )

    assert response.status_code == 200
    assert response.json()["output"] == service_output


@pytest.mark.asyncio
async def test_download_agent_uses_caller_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = create_app()
    set_expected_api_token(app, "gateway-token")
    service_output = {
        "is_download_request": True,
        "requested_subtitle_language": "en",
        "requested_dub_language": None,
        "assistant_text": "Preparing the video.",
    }

    class DownloadStub(StubGenerationService):
        async def generate(self, command: GenerateCommand) -> GenerateResult:
            self.commands.append(command)
            return GenerateResult(
                request_id=command.request_id,
                output=service_output,
                provider="qwen",
                model="Qwen/Qwen3-4B-Instruct-2507",
                provider_request_id=command.request_id,
                usage=LLMTokenUsage(input_tokens=5, output_tokens=3, total_tokens=8),
            )

    download_service = DownloadStub()
    monkeypatch.setattr(
        "telegram_agent.core.llm_gateway.api.v1.download_agent.router.get_download_agent_service",
        lambda media_type: download_service,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/v1/download-agent",
            headers={"Authorization": "Bearer gateway-token"},
            json={
                "system_prompt": "system",
                "user_prompt": "user",
                "media_type": "video",
                "idempotency_key": "download-agent:abc",
            },
        )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "download-agent:abc"
    assert response.json()["request_id"] == "download-agent:abc"
    assert response.json()["provider"] == "qwen"
    assert download_service.commands[0].request_id == "download-agent:abc"


@pytest.mark.asyncio
async def test_readiness_openai_requires_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_gateway_service_token", "gateway-token")
    monkeypatch.setattr(settings, "download_agent_backend", "openai")
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


@pytest.mark.asyncio
async def test_readiness_local_does_not_require_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "llm_gateway_service_token", "gateway-token")
    monkeypatch.setattr(settings, "download_agent_backend", "local")
    monkeypatch.setattr(settings, "openai_api_key", None)
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
