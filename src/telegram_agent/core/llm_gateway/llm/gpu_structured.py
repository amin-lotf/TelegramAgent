from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from telegram_agent.core.common.gpu_workloads import QWEN_STRUCTURED_GENERATION_WORKLOAD
from telegram_agent.core.llm_gateway.clients.gpu_execution import GpuExecutionClient
from telegram_agent.core.llm_gateway.common.exceptions import (
    InvalidLlmGatewayRequestError,
    LlmGatewayAuthenticationError,
    RetryableLlmGatewayError,
)
from telegram_agent.core.llm_gateway.common.results import LLMGenerateResult, LLMTokenUsage
from telegram_agent.core.llm_gateway.common.settings import Settings
from telegram_agent.core.llm_gateway.common.settings import settings as default_settings

_SAFE_REQUEST_ID = re.compile(r"[^A-Za-z0-9._-]+")


class GpuStructuredLlm:
    """Structured LLM adapter that submits a Qwen GPU workload and validates the result."""

    def __init__(
        self,
        *,
        schema: type[BaseModel],
        gpu_client: GpuExecutionClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._schema = schema
        self._settings = settings or default_settings
        if gpu_client is None:
            if self._settings.gpu_execution_service_token is None:
                raise LlmGatewayAuthenticationError(
                    "GPU execution is not configured for local download-agent generation"
                )
            gpu_client = GpuExecutionClient(self._settings)
        self._gpu_client = gpu_client

    async def ainvoke(self, input: Any, **kwargs: Any) -> LLMGenerateResult:
        request_id = _request_id(kwargs.get("request_id"))
        system_prompt, user_prompt = _split_messages(input)
        storage_root = self._settings.gpu_shared_storage_root.expanduser()
        job_dir = storage_root / "llm_gateway" / _safe_request_id(request_id)
        input_path = job_dir / "input.json"
        output_path = job_dir / "output.json"
        _write_json_atomic(
            input_path,
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "json_schema": self._schema.model_json_schema(),
                "max_validation_attempts": (
                    self._settings.download_agent_local_max_validation_attempts
                ),
                "max_new_tokens": self._settings.download_agent_local_max_new_tokens,
                "temperature": self._settings.reply_temperature,
            },
        )
        result_path = await self._gpu_client.execute_and_wait(
            workload_type=QWEN_STRUCTURED_GENERATION_WORKLOAD,
            idempotency_key=f"{QWEN_STRUCTURED_GENERATION_WORKLOAD}:{request_id}",
            input_path=input_path,
            output_path=output_path,
            parameters={"model": self._settings.download_agent_local_model},
            timeout_seconds=self._settings.download_agent_local_job_timeout_seconds,
            max_attempts=self._settings.download_agent_local_job_max_attempts,
        )
        payload = _load_result(result_path)
        raw_output = payload.get("output")
        try:
            parsed = self._schema.model_validate(raw_output)
        except ValidationError as exc:
            raise RetryableLlmGatewayError(
                "Local structured generation output failed schema validation"
            ) from exc
        model = payload.get("model")
        usage_payload = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
        return LLMGenerateResult(
            output=parsed,
            model=str(model) if isinstance(model, str) and model else (
                self._settings.download_agent_local_model
            ),
            provider_request_id=request_id,
            usage=_token_usage(usage_payload),
        )


def _split_messages(messages: Any) -> tuple[str, str]:
    if not isinstance(messages, list):
        raise InvalidLlmGatewayRequestError(
            "Structured generation input must be a chat message list"
        )
    system_prompt = ""
    user_parts: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if role == "system" and not system_prompt:
            system_prompt = content
        elif role == "user":
            user_parts.append(content)
    if not system_prompt.strip() or not user_parts:
        raise InvalidLlmGatewayRequestError(
            "Structured generation requires system and user prompts"
        )
    return system_prompt, "\n\n".join(user_parts)


def _request_id(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return str(uuid4())


def _safe_request_id(request_id: str) -> str:
    sanitized = _SAFE_REQUEST_ID.sub("_", request_id).strip("._")
    return sanitized or "request"


def _write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _load_result(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetryableLlmGatewayError(
            "Local structured generation output could not be read"
        ) from exc
    if not isinstance(payload, dict):
        raise RetryableLlmGatewayError(
            "Local structured generation output was not a JSON object"
        )
    return payload


def _token_usage(raw: dict[str, Any]) -> LLMTokenUsage:
    def _as_int(value: object) -> int:
        try:
            parsed = int(value or 0)
        except (TypeError, ValueError):
            return 0
        return max(parsed, 0)

    input_tokens = _as_int(raw.get("input_tokens"))
    output_tokens = _as_int(raw.get("output_tokens"))
    total_tokens = raw.get("total_tokens")
    if total_tokens is None:
        total = input_tokens + output_tokens
    else:
        total = _as_int(total_tokens)
    return LLMTokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )
