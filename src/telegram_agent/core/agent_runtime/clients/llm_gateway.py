from __future__ import annotations

import httpx
from pydantic import ValidationError

from telegram_agent.core.agent_runtime.clients.models import LlmGatewayGeneration
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)


class LlmGatewayClient:
    """Synchronous transport adapter for agent-runtime LLM generation use cases."""

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
        return self._post_generation(
            path="/message-grouping",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            unavailable_message="LLM coordination is temporarily unavailable",
            auth_failed_message="LLM gateway authentication failed",
            rejected_message="LLM gateway rejected the coordination request",
            invalid_response_message="LLM gateway returned an invalid generation response",
        )

    def classify_intent(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmGatewayGeneration:
        return self._post_generation(
            path="/intent-classification",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            unavailable_message="LLM intent classification is temporarily unavailable",
            auth_failed_message="LLM gateway authentication failed",
            rejected_message="LLM gateway rejected the intent classification request",
            invalid_response_message=(
                "LLM gateway returned an invalid intent classification response"
            ),
        )

    def _post_generation(
        self,
        *,
        path: str,
        system_prompt: str,
        user_prompt: str,
        unavailable_message: str,
        auth_failed_message: str,
        rejected_message: str,
        invalid_response_message: str,
    ) -> LlmGatewayGeneration:
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}{path}",
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
                    unavailable_message
                ) from exc
            if status_code in {401, 403}:
                raise PermanentAgentRuntimeCoordinationError(
                    auth_failed_message
                ) from exc
            raise PermanentAgentRuntimeCoordinationError(rejected_message) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableAgentRuntimeCoordinationError(unavailable_message) from exc
        except httpx.RequestError as exc:
            raise RetryableAgentRuntimeCoordinationError(unavailable_message) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise RetryableAgentRuntimeCoordinationError(
                invalid_response_message
            ) from exc
