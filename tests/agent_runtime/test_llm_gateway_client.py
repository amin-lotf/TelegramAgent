from __future__ import annotations

import json

import httpx
import pytest

from telegram_agent.core.agent_runtime.clients.llm_gateway import LlmGatewayClient
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)


def _client(handler) -> LlmGatewayClient:
    return LlmGatewayClient(
        base_url="http://llm-gateway.test/v1",
        token="service-token",
        timeout_seconds=3,
        transport=httpx.MockTransport(handler),
    )


def _coordinate(client: LlmGatewayClient):
    return client.coordinate_message_group(
        system_prompt="system",
        user_prompt="user",
    )


def test_coordinate_sends_authenticated_prompt_only_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://llm-gateway.test/v1/message-grouping"
        assert request.headers["Authorization"] == "Bearer service-token"
        payload = json.loads(request.content)
        assert payload == {
            "system_prompt": "system",
            "user_prompt": "user",
        }
        assert "model_profile" not in payload
        assert "response_schema" not in payload
        assert "temperature" not in payload
        return httpx.Response(
            200,
            json={
                "request_id": "request-1",
                "output": {"kind": "new", "group_number": None},
                "provider": "openai",
                "model": "provider-model",
                "provider_request_id": "provider-request-1",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            },
        )

    result = _coordinate(_client(handler))

    assert result.output == {"kind": "new", "group_number": None}
    assert result.provider == "openai"
    assert result.usage.total_tokens == 12


@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
def test_retryable_statuses_are_coordination_retryable(status_code: int) -> None:
    client = _client(lambda _: httpx.Response(status_code, json={"detail": "no"}))

    with pytest.raises(RetryableAgentRuntimeCoordinationError):
        _coordinate(client)


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422, 424])
def test_authentication_and_invalid_requests_are_permanent(status_code: int) -> None:
    client = _client(lambda _: httpx.Response(status_code, json={"detail": "no"}))

    with pytest.raises(PermanentAgentRuntimeCoordinationError):
        _coordinate(client)


def test_connection_failure_is_coordination_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(RetryableAgentRuntimeCoordinationError):
        _coordinate(_client(handler))


def test_invalid_success_response_is_coordination_retryable() -> None:
    client = _client(lambda _: httpx.Response(200, json={"unexpected": True}))

    with pytest.raises(RetryableAgentRuntimeCoordinationError):
        _coordinate(client)


def test_extract_download_request_sends_media_type_and_idempotency_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://llm-gateway.test/v1/download-agent"
        payload = json.loads(request.content)
        assert payload == {
            "system_prompt": "system",
            "user_prompt": "user",
            "media_type": "video",
            "idempotency_key": "download-agent:abc",
        }
        return httpx.Response(
            200,
            json={
                "request_id": "download-agent:abc",
                "output": {
                    "is_download_request": True,
                    "assistant_text": "Preparing the video.",
                    "requested_subtitle_language": "en",
                    "requested_dub_language": None,
                },
                "provider": "qwen",
                "model": "Qwen/Qwen3-4B-Instruct-2507",
                "provider_request_id": "download-agent:abc",
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 2,
                    "total_tokens": 12,
                },
            },
        )

    result = _client(handler).extract_download_request(
        system_prompt="system",
        user_prompt="user",
        media_type="video",
        idempotency_key="download-agent:abc",
    )
    assert result.provider == "qwen"
    assert result.request_id == "download-agent:abc"
