from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)


class LlmGatewayTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class LlmGatewayGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    output: dict[str, Any]
    provider: str
    model: str
    provider_request_id: str | None = None
    usage: LlmGatewayTokenUsage


class LlmGatewayClient:
    """Synchronous transport adapter for content-processing LLM use cases."""

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

    def extract_glossary(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmGatewayGeneration:
        return self._post_generation(
            path="/glossary-extraction",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            unavailable_message="LLM glossary extraction is temporarily unavailable",
            auth_failed_message="LLM gateway authentication failed",
            rejected_message="LLM gateway rejected the glossary extraction request",
            invalid_response_message=(
                "LLM gateway returned an invalid glossary extraction response"
            ),
        )

    def translate_subtitle_batch(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmGatewayGeneration:
        return self._post_generation(
            path="/subtitle-translation",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            unavailable_message="LLM subtitle translation is temporarily unavailable",
            auth_failed_message="LLM gateway authentication failed",
            rejected_message="LLM gateway rejected the subtitle translation request",
            invalid_response_message=(
                "LLM gateway returned an invalid subtitle translation response"
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
        payload = {
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        try:
            with httpx.Client(
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = client.post(
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=payload,
                )
            response.raise_for_status()
            return LlmGatewayGeneration.model_validate(response.json())
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            if status_code in {408, 429} or status_code >= 500:
                raise RetryableContentProcessingError(unavailable_message) from exc
            if status_code in {401, 403}:
                raise PermanentContentProcessingError(auth_failed_message) from exc
            raise PermanentContentProcessingError(rejected_message) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableContentProcessingError(unavailable_message) from exc
        except httpx.RequestError as exc:
            raise RetryableContentProcessingError(unavailable_message) from exc
        except (ValueError, TypeError, ValidationError) as exc:
            raise RetryableContentProcessingError(invalid_response_message) from exc
