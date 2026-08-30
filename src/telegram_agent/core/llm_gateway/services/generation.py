from __future__ import annotations

import logging
from time import monotonic
from typing import Any, Protocol

from pydantic import BaseModel

from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.exceptions import RetryableLlmGatewayError
from telegram_agent.core.llm_gateway.common.results import GenerateResult, LLMGenerateResult

logger = logging.getLogger(__name__)


class StructuredLlm(Protocol):
    async def ainvoke(self, input: Any, **kwargs: Any) -> LLMGenerateResult:
        """Invoke the structured LLM and return a uniform generation result."""


class GenerationService:
    def __init__(
        self,
        *,
        llm: StructuredLlm,
        provider_name: str = "openai",
    ) -> None:
        self._llm = llm
        self._provider_name = provider_name

    async def generate(self, command: GenerateCommand) -> GenerateResult:
        started_at = monotonic()
        messages = [
            {"role": "system", "content": command.system_prompt},
            {"role": "user", "content": command.user_prompt},
        ]
        generation = await self._llm.ainvoke(messages, request_id=command.request_id)
        output = self._serialize_output(generation.output)

        elapsed_ms = round((monotonic() - started_at) * 1000)
        logger.info(
            "Completed structured LLM generation",
            extra={
                "request_id": command.request_id,
                "provider": self._provider_name,
                "model": generation.model,
                "elapsed_ms": elapsed_ms,
                "input_tokens": generation.usage.input_tokens,
                "output_tokens": generation.usage.output_tokens,
            },
        )
        return GenerateResult(
            request_id=command.request_id,
            output=output,
            provider=self._provider_name,
            model=generation.model,
            provider_request_id=generation.provider_request_id,
            usage=generation.usage,
        )

    @staticmethod
    def _serialize_output(output: Any) -> dict[str, Any]:
        if isinstance(output, BaseModel):
            return output.model_dump(mode="json")
        if isinstance(output, dict):
            return output
        raise RetryableLlmGatewayError(
            "Structured generation output was not a structured object"
        )
