from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import openai
from langchain_openai import OpenAIEmbeddings

from telegram_agent.core.embedding.common.const import OPENAI_PROVIDER
from telegram_agent.core.embedding.common.exceptions import (
    EmbeddingAuthenticationError,
    EmbeddingError,
    InvalidEmbeddingRequestError,
    PermanentEmbeddingError,
    RetryableEmbeddingError,
)
from telegram_agent.core.embedding.common.settings import Settings, settings


def _map_openai_error(exc: BaseException) -> EmbeddingError | None:
    """Translate OpenAI SDK errors into embedding exceptions. Returns None if unknown."""
    if isinstance(
        exc,
        (
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.RateLimitError,
            openai.InternalServerError,
        ),
    ):
        return RetryableEmbeddingError("OpenAI embeddings are temporarily unavailable")
    if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
        return EmbeddingAuthenticationError(
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
        return InvalidEmbeddingRequestError("OpenAI rejected the embedding request")
    if isinstance(exc, openai.APIStatusError):
        if exc.status_code in {408, 409, 429} or exc.status_code >= 500:
            return RetryableEmbeddingError(
                "OpenAI embeddings are temporarily unavailable"
            )
        return PermanentEmbeddingError("OpenAI rejected the embedding request")
    if isinstance(exc, openai.APIError):
        return RetryableEmbeddingError("OpenAI returned an invalid API response")
    return None


class OpenAIEmbeddingProvider:
    """Embedding backend backed by langchain OpenAIEmbeddings."""

    provider_name = OPENAI_PROVIDER

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 2,
        dimensions: int | None = None,
    ) -> None:
        self.model_name = model
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": api_key,
            "max_retries": max_retries,
        }
        if base_url is not None:
            kwargs["base_url"] = base_url
        if timeout is not None:
            kwargs["timeout"] = timeout
        if dimensions is not None:
            kwargs["dimensions"] = dimensions
        self._default_dimensions = dimensions
        self._embeddings = OpenAIEmbeddings(**kwargs)

    @classmethod
    def from_settings(
        cls,
        app_settings: Settings | None = None,
        *,
        model: str | None = None,
        dimensions: int | None = None,
    ) -> "OpenAIEmbeddingProvider":
        cfg = app_settings or settings
        if cfg.openai_api_key is None:
            raise EmbeddingAuthenticationError("Embedding provider is not configured")
        resolved_model = model or cfg.embedding_model
        resolved_dimensions = (
            dimensions if dimensions is not None else cfg.embedding_dimensions
        )
        return cls(
            model=resolved_model,
            api_key=cfg.openai_api_key,
            base_url=cfg.openai_base_url,
            timeout=cfg.openai_request_timeout_seconds,
            max_retries=cfg.openai_max_retries,
            dimensions=resolved_dimensions,
        )

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        dimensions: int | None = None,
    ) -> Sequence[Sequence[float]]:
        if not texts:
            return ()

        # dimensions is fixed at construction for OpenAIEmbeddings; callers that
        # need a different size should construct a provider with that size.
        _ = dimensions

        try:
            vectors = await self._embeddings.aembed_documents(list(texts))
        except Exception as exc:
            mapped = _map_openai_error(exc)
            if mapped is not None:
                raise mapped from exc
            raise RetryableEmbeddingError(
                "OpenAI embeddings are temporarily unavailable"
            ) from exc

        if len(vectors) != len(texts):
            raise RetryableEmbeddingError(
                "OpenAI returned an unexpected number of embeddings"
            )
        return vectors
