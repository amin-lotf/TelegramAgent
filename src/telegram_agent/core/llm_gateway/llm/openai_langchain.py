from __future__ import annotations

import time
from typing import Any, Mapping

import openai
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

from telegram_agent.core.llm_gateway.common.exceptions import (
    InvalidLlmGatewayRequestError,
    LlmGatewayAuthenticationError,
    LlmGatewayError,
    PermanentLlmGatewayError,
    RetryableLlmGatewayError,
)
from telegram_agent.core.llm_gateway.common.results import LLMGenerateResult, LLMTokenUsage
from telegram_agent.core.llm_gateway.common.settings import settings


def _map_openai_error(exc: BaseException) -> LlmGatewayError | None:
    """Translate OpenAI SDK errors into gateway exceptions. Returns None if unknown."""
    if isinstance(
        exc,
        (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ),
    ):
        return RetryableLlmGatewayError("OpenAI is temporarily unavailable")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return LlmGatewayAuthenticationError(
            "OpenAI credentials or permissions are invalid"
        )
    if isinstance(
        exc,
        (
            openai.BadRequestError,
            openai.NotFoundError,
            openai.UnprocessableEntityError,
        ),
    ):
        return InvalidLlmGatewayRequestError("OpenAI rejected the generation request")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in {408, 409, 429} or exc.status_code >= 500:
            return RetryableLlmGatewayError("OpenAI is temporarily unavailable")
        return PermanentLlmGatewayError("OpenAI rejected the generation request")
    if isinstance(exc, openai.APIError):
        return RetryableLlmGatewayError("OpenAI returned an invalid API response")
    return None


class TimedChatOpenAI:
    """
    Lightweight wrapper around ChatOpenAI.

    Records token usage when available. ``ainvoke`` always returns
    :class:`LLMGenerateResult`. ``with_structured_output`` returns a
    :class:`TimedStructuredRunnable` with the same result shape.
    """

    def __init__(self, inner: ChatOpenAI) -> None:
        self._inner = inner
        self._default_model: str = (
            getattr(inner, "model_name", None)
            or getattr(inner, "model", None)
            or "unknown"
        )

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)

    @staticmethod
    def _extract_usage_metadata(value: Any) -> LLMTokenUsage | None:
        usage_metadata = getattr(value, "usage_metadata", None)

        if isinstance(usage_metadata, Mapping):
            return TimedChatOpenAI._to_token_usage(usage_metadata)

        if isinstance(value, Mapping):
            usage_metadata = value.get("usage_metadata")
            if isinstance(usage_metadata, Mapping):
                return TimedChatOpenAI._to_token_usage(usage_metadata)

        response_metadata = getattr(value, "response_metadata", None)

        if not isinstance(response_metadata, Mapping) and isinstance(value, Mapping):
            response_metadata = value.get("response_metadata")

        if not isinstance(response_metadata, Mapping):
            return None

        token_usage = response_metadata.get("token_usage") or response_metadata.get(
            "usage"
        )
        if not isinstance(token_usage, Mapping):
            return None

        return TimedChatOpenAI._to_token_usage(token_usage)

    @staticmethod
    def _to_token_usage(raw: Mapping[str, Any]) -> LLMTokenUsage:
        input_tokens = (
            raw.get("input_tokens")
            if raw.get("input_tokens") is not None
            else raw.get("prompt_tokens")
        )
        output_tokens = (
            raw.get("output_tokens")
            if raw.get("output_tokens") is not None
            else raw.get("completion_tokens")
        )
        total_tokens = raw.get("total_tokens")

        input_tokens = int(input_tokens or 0)
        output_tokens = int(output_tokens or 0)
        if total_tokens is None:
            total_tokens = input_tokens + output_tokens
        else:
            total_tokens = int(total_tokens)

        return LLMTokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )

    @staticmethod
    def _extract_model(value: Any) -> str | None:
        response_metadata = getattr(value, "response_metadata", None)
        if not isinstance(response_metadata, Mapping) and isinstance(value, Mapping):
            response_metadata = value.get("response_metadata")
        if isinstance(response_metadata, Mapping):
            model = response_metadata.get("model_name") or response_metadata.get(
                "model"
            )
            if isinstance(model, str) and model:
                return model
        return None

    @staticmethod
    def _extract_request_id(value: Any) -> str | None:
        msg_id = getattr(value, "id", None)
        if isinstance(msg_id, str) and msg_id:
            return msg_id

        response_metadata = getattr(value, "response_metadata", None)
        if not isinstance(response_metadata, Mapping) and isinstance(value, Mapping):
            response_metadata = value.get("response_metadata")
        if isinstance(response_metadata, Mapping):
            rid = response_metadata.get("id") or response_metadata.get("request_id")
            if isinstance(rid, str) and rid:
                return rid
        return None

    def bind_tools(self, *args: Any, **kwargs: Any) -> Any:
        bound = self._inner.bind_tools(*args, **kwargs)
        return TimedChatOpenAI(bound)

    def with_structured_output(
        self, schema: Any, **kwargs: Any
    ) -> "TimedStructuredRunnable":
        structured = self._inner.with_structured_output(
            schema,
            include_raw=True,
            **kwargs,
        )
        return TimedStructuredRunnable(structured, default_model=self._default_model)

    async def ainvoke(
        self,
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        started_at = time.perf_counter()

        try:
            result = await self._inner.ainvoke(input, config=config, **kwargs)

            usage = self._extract_usage_metadata(result)
            if usage is None:
                usage = LLMTokenUsage(
                    input_tokens=0, output_tokens=0, total_tokens=0
                )

            model = self._extract_model(result) or self._default_model
            provider_request_id = self._extract_request_id(result)

            _ = time.perf_counter() - started_at

            return LLMGenerateResult(
                output=result,
                model=model,
                provider_request_id=provider_request_id,
                usage=usage,
            )
        except Exception as exc:
            mapped = _map_openai_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise


class TimedStructuredRunnable:
    """
    Wrapper for the runnable returned by ``with_structured_output(include_raw=True)``.

    LangChain returns::

        {
            "raw": AIMessage,
            "parsed": <Pydantic / schema instance>,
            "parsing_error": Exception | None,
        }

    Harvests token usage / model / request_id from ``raw`` and returns
    :class:`LLMGenerateResult` with ``output=parsed``.
    """

    def __init__(self, inner: Any, default_model: str = "unknown") -> None:
        self._inner = inner
        self._default_model = default_model

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._inner, attr)

    async def ainvoke(
        self,
        input: Any,
        config: RunnableConfig | None = None,
        **kwargs: Any,
    ) -> LLMGenerateResult:
        started_at = time.perf_counter()

        try:
            result = await self._inner.ainvoke(input, config=config, **kwargs)

            raw = result.get("raw") if isinstance(result, Mapping) else None
            parsed = result.get("parsed") if isinstance(result, Mapping) else result
            parsing_error = (
                result.get("parsing_error") if isinstance(result, Mapping) else None
            )

            if parsing_error is not None:
                raise RetryableLlmGatewayError(
                    "Structured output could not be parsed"
                ) from parsing_error

            usage = TimedChatOpenAI._extract_usage_metadata(raw)
            if usage is None:
                usage = LLMTokenUsage(
                    input_tokens=0, output_tokens=0, total_tokens=0
                )

            model = TimedChatOpenAI._extract_model(raw) or self._default_model
            provider_request_id = TimedChatOpenAI._extract_request_id(raw)

            _ = time.perf_counter() - started_at

            return LLMGenerateResult(
                output=parsed,
                model=model,
                provider_request_id=provider_request_id,
                usage=usage,
            )
        except LlmGatewayError:
            raise
        except Exception as exc:
            mapped = _map_openai_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise


_operator: TimedChatOpenAI | None = None


def get_operator() -> TimedChatOpenAI:
    """Return the process-wide ChatOpenAI operator (lazy, requires API key)."""
    global _operator
    if _operator is None:
        if settings.openai_api_key is None:
            from telegram_agent.core.llm_gateway.common.exceptions import (
                LlmGatewayAuthenticationError,
            )

            raise LlmGatewayAuthenticationError("LLM provider is not configured")
        kwargs: dict[str, Any] = {
            "model": settings.reply_model,
            "temperature": settings.reply_temperature,
            "api_key": settings.openai_api_key,
            "stream_usage": True,
            "max_retries": settings.openai_max_retries,
            "timeout": settings.openai_request_timeout_seconds,
        }
        if settings.openai_base_url is not None:
            kwargs["base_url"] = settings.openai_base_url
        _operator = TimedChatOpenAI(ChatOpenAI(**kwargs))
    return _operator
