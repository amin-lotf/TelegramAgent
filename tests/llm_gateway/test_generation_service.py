from __future__ import annotations

from typing import Any

import pytest

from telegram_agent.core.llm_gateway.common.commands import GenerateCommand
from telegram_agent.core.llm_gateway.common.exceptions import RetryableLlmGatewayError
from telegram_agent.core.llm_gateway.common.results import LLMGenerateResult, LLMTokenUsage
from telegram_agent.core.llm_gateway.common.schemas import (
    MessageGroupingKind,
    MessageGroupingResponse,
)
from telegram_agent.core.llm_gateway.services.generation import GenerationService


class StubStructuredLlm:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[Any] = []

    async def ainvoke(self, input: Any, **kwargs: Any) -> LLMGenerateResult:
        self.calls.append(input)
        return LLMGenerateResult(
            output=self.output,
            model="stub-model",
            provider_request_id="provider-request",
            usage=LLMTokenUsage(input_tokens=4, output_tokens=2, total_tokens=6),
        )


def _command() -> GenerateCommand:
    return GenerateCommand(
        request_id="gateway-request",
        system_prompt="system",
        user_prompt="user",
    )


@pytest.mark.asyncio
async def test_generate_serializes_pydantic_output_and_returns_metadata() -> None:
    llm = StubStructuredLlm(
        MessageGroupingResponse(kind=MessageGroupingKind.NEW, group_number=None)
    )
    service = GenerationService(llm=llm, provider_name="stub")

    result = await service.generate(_command())

    assert llm.calls[0] == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "user"},
    ]
    assert result.output == {"kind": "new", "group_number": None}
    assert result.provider == "stub"
    assert result.model == "stub-model"
    assert result.provider_request_id == "provider-request"
    assert result.usage.total_tokens == 6


@pytest.mark.asyncio
async def test_generate_accepts_dict_output() -> None:
    llm = StubStructuredLlm({"kind": "vague", "group_number": None})
    service = GenerationService(llm=llm)

    result = await service.generate(_command())

    assert result.output == {"kind": "vague", "group_number": None}


@pytest.mark.asyncio
async def test_non_object_output_is_retryable() -> None:
    llm = StubStructuredLlm("not-an-object")
    service = GenerationService(llm=llm)

    with pytest.raises(RetryableLlmGatewayError):
        await service.generate(_command())


@pytest.mark.asyncio
async def test_retryable_llm_failure_propagates() -> None:
    class FailingLlm:
        async def ainvoke(self, input: Any, **kwargs: Any) -> LLMGenerateResult:
            raise RetryableLlmGatewayError("temporary")

    service = GenerationService(llm=FailingLlm())

    with pytest.raises(RetryableLlmGatewayError):
        await service.generate(_command())
