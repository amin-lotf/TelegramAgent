from __future__ import annotations

import httpx
from pydantic import ValidationError

from telegram_agent.core.agent_runtime.clients.models import LlmGatewayGeneration
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)


class LlmGatewayClient:
    """Synchronous transport adapter for message-grouping LLM generation."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    def coordinate_message_group(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmGatewayGeneration:
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}/message-grouping",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json={
                        "system_prompt": system_prompt,
                        "user_prompt": user_prompt,
                    },
                )
            response.raise_for_status()
            return LlmGatewayGeneration.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 429} or status_code >= 500:
                raise RetryableAgentRuntimeCoordinationError(
                    "LLM coordination is temporarily unavailable"
                ) from exc
            if status_code in {401, 403}:
                raise PermanentAgentRuntimeCoordinationError(
                    "LLM gateway authentication failed"
                ) from exc
            raise PermanentAgentRuntimeCoordinationError(
                "LLM gateway rejected the coordination request"
            ) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableAgentRuntimeCoordinationError(
                "LLM coordination is temporarily unavailable"
            ) from exc
        except httpx.RequestError as exc:
            raise RetryableAgentRuntimeCoordinationError(
                "LLM coordination is temporarily unavailable"
            ) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise RetryableAgentRuntimeCoordinationError(
                "LLM gateway returned an invalid generation response"
            ) from exc
