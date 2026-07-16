from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from telegram_agent.core.llm_gateway.api.v1.fastapi_app import create_app
from telegram_agent.core.llm_gateway.api.v1.message_grouping.dependencies import (
    get_message_grouping_service,
)
from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.results import GenerateResult, LLMTokenUsage
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
