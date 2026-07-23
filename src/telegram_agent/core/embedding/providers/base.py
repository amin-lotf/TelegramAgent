from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Transport-agnostic interface for embedding backends."""

    provider_name: str
    model_name: str

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        dimensions: int | None = None,
    ) -> Sequence[Sequence[float]]:
        """Return one embedding vector per input text, in order."""
        ...
