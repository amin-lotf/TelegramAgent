from __future__ import annotations


class LlmGatewayError(RuntimeError):
    """Base class for failures exposed by the LLM gateway application layer."""


class RetryableLlmGatewayError(LlmGatewayError):
    """A transient generation or provider failure that may succeed when repeated."""


class InvalidLlmGatewayRequestError(LlmGatewayError):
    """A request the gateway cannot satisfy as submitted."""


class LlmGatewayAuthenticationError(LlmGatewayError):
    """Configured LLM credentials or permissions are invalid."""


class PermanentLlmGatewayError(LlmGatewayError):
    """A non-retryable generation failure unrelated to caller authentication."""
