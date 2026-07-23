from __future__ import annotations


class EmbeddingError(RuntimeError):
    """Base class for failures exposed by the embedding application layer."""


class RetryableEmbeddingError(EmbeddingError):
    """A transient provider failure that may succeed when repeated."""


class InvalidEmbeddingRequestError(EmbeddingError):
    """A request the embedding service cannot satisfy as submitted."""


class EmbeddingAuthenticationError(EmbeddingError):
    """Configured embedding provider credentials or permissions are invalid."""


class PermanentEmbeddingError(EmbeddingError):
    """A non-retryable provider failure unrelated to caller authentication."""
