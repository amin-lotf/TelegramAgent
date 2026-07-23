from __future__ import annotations

from telegram_agent.core.embedding.common.commands import EmbedOptions
from telegram_agent.core.embedding.common.settings import settings
from telegram_agent.core.embedding.providers.openai import OpenAIEmbeddingProvider
from telegram_agent.core.embedding.services.embedding import EmbeddingService


def _openai_provider_factory(options: EmbedOptions) -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider.from_settings(
        settings,
        model=options.model,
        dimensions=options.dimensions,
    )


def get_embedding_service() -> EmbeddingService:
    return EmbeddingService(provider_factory=_openai_provider_factory)
