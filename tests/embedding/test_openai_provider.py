from __future__ import annotations

import openai
import httpx

from telegram_agent.core.embedding.common.exceptions import (
    EmbeddingAuthenticationError,
    InvalidEmbeddingRequestError,
    PermanentEmbeddingError,
    RetryableEmbeddingError,
)
from telegram_agent.core.embedding.providers.openai import _map_openai_error


def _response(status_code: int = 400) -> httpx.Response:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    return httpx.Response(status_code=status_code, request=request)


def test_map_timeout_is_retryable() -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
    mapped = _map_openai_error(openai.APITimeoutError(request=request))
    assert isinstance(mapped, RetryableEmbeddingError)


def test_map_auth_error() -> None:
    mapped = _map_openai_error(
        openai.AuthenticationError(
            message="bad key",
            response=_response(401),
            body=None,
        )
    )
    assert isinstance(mapped, EmbeddingAuthenticationError)


def test_map_bad_request() -> None:
    mapped = _map_openai_error(
        openai.BadRequestError(
            message="bad request",
            response=_response(400),
            body=None,
        )
    )
    assert isinstance(mapped, InvalidEmbeddingRequestError)


def test_map_unknown_returns_none() -> None:
    assert _map_openai_error(RuntimeError("nope")) is None


def test_map_status_error_5xx_is_retryable() -> None:
    mapped = _map_openai_error(
        openai.APIStatusError(
            message="unavailable",
            response=_response(503),
            body=None,
        )
    )
    assert isinstance(mapped, RetryableEmbeddingError)


def test_map_status_error_4xx_is_permanent() -> None:
    mapped = _map_openai_error(
        openai.APIStatusError(
            message="bad",
            response=_response(400),
            body=None,
        )
    )
    assert isinstance(mapped, PermanentEmbeddingError)
