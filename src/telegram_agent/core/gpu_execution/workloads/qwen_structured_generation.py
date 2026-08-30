"""GPU workload: load Qwen, emit schema-constrained JSON, then exit."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)
from telegram_agent.core.gpu_execution.workloads.qwen_engine import (
    DEFAULT_DEVICE,
    DEFAULT_MODEL_ID,
    QwenEngineError,
    QwenStructuredEngine,
)

logger = logging.getLogger(__name__)

_DEFAULT_MAX_VALIDATION_ATTEMPTS = 3
_DEFAULT_MAX_NEW_TOKENS = 512
_DEFAULT_TEMPERATURE = 0.2
_RETRY_TEMPERATURE_STEP = 0.2
_RETRY_TEMPERATURE_MAX = 0.7


class QwenStructuredGenerationWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        payload = _load_object(input_path)
        system_prompt = _required_string(payload.get("system_prompt"), field="system_prompt")
        user_prompt = _required_string(payload.get("user_prompt"), field="user_prompt")
        json_schema = payload.get("json_schema")
        if not isinstance(json_schema, dict) or not json_schema:
            raise GpuWorkloadPermanentError("Qwen json_schema must be a JSON object")

        model_id = str(
            parameters.get("model") or os.getenv("QWEN_MODEL_ID", DEFAULT_MODEL_ID)
        ).strip()
        installed_model = os.getenv("QWEN_MODEL_ID", DEFAULT_MODEL_ID).strip()
        if model_id != installed_model:
            raise GpuWorkloadPermanentError(
                f"Qwen model {model_id!r} is not installed in this worker"
            )

        max_validation_attempts = _positive_int(
            payload.get("max_validation_attempts"),
            default=_DEFAULT_MAX_VALIDATION_ATTEMPTS,
            field="max_validation_attempts",
        )
        max_new_tokens = _positive_int(
            payload.get("max_new_tokens"),
            default=_DEFAULT_MAX_NEW_TOKENS,
            field="max_new_tokens",
        )
        temperature = _temperature(
            payload.get("temperature"),
            default=_DEFAULT_TEMPERATURE,
        )

        engine = _build_engine(model_id=model_id)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        parsed: dict[str, Any] | None = None
        usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        attempts = 0
        last_error = "Qwen did not return schema-valid JSON"
        try:
            engine.load()
            for attempts in range(1, max_validation_attempts + 1):
                try:
                    parsed, usage = engine.generate_json(
                        messages,
                        json_schema,
                        max_new_tokens=max_new_tokens,
                        temperature=temperature,
                    )
                    validate_against_schema(parsed, json_schema)
                    break
                except (QwenEngineError, ValueError) as exc:
                    last_error = str(exc)
                    logger.warning(
                        "Qwen structured generation attempt %s/%s failed: %s",
                        attempts,
                        max_validation_attempts,
                        exc,
                    )
                    if attempts >= max_validation_attempts:
                        parsed = None
                        break
                    messages = [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "The previous JSON was invalid: "
                                f"{last_error}. Return only valid JSON matching the schema."
                            ),
                        },
                    ]
                    temperature = min(
                        _RETRY_TEMPERATURE_MAX,
                        temperature + _RETRY_TEMPERATURE_STEP,
                    )
        except GpuWorkloadPermanentError:
            raise
        except RuntimeError as exc:
            message = str(exc)
            if "CUDA" in message or "cuda" in message.lower():
                raise GpuWorkloadRetryableError(message) from exc
            raise GpuWorkloadPermanentError(message) from exc
        finally:
            engine.close()

        if parsed is None:
            raise GpuWorkloadRetryableError(
                f"Qwen structured generation failed validation: {last_error}"
            )

        _write_json_atomic(
            output_path,
            {
                "output": parsed,
                "model": model_id,
                "attempts": attempts,
                "usage": usage,
            },
        )
        logger.info(
            "Qwen structured generation complete model=%s attempts=%s",
            model_id,
            attempts,
        )


def create_handler() -> GpuWorkloadHandler:
    return QwenStructuredGenerationWorkload()


def _build_engine(*, model_id: str) -> QwenStructuredEngine:
    device = os.getenv("QWEN_DEVICE", DEFAULT_DEVICE).strip() or DEFAULT_DEVICE
    return QwenStructuredEngine(
        model_id=model_id,
        device=device,
        hf_token=os.environ.get("HF_TOKEN") or None,
    )


def validate_against_schema(instance: object, schema: dict[str, Any]) -> None:
    defs = schema.get("$defs") or schema.get("definitions") or {}
    if not isinstance(defs, dict):
        defs = {}
    _validate(instance, schema, defs)


def _validate(instance: object, schema: dict[str, Any], defs: dict[str, Any]) -> None:
    schema = _resolve(schema, defs)
    if "anyOf" in schema:
        options = schema["anyOf"]
        if not isinstance(options, list) or not options:
            raise ValueError("JSON schema anyOf must be a non-empty list")
        errors: list[str] = []
        for option in options:
            if not isinstance(option, dict):
                errors.append("anyOf option must be an object")
                continue
            try:
                _validate(instance, option, defs)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(errors[-1] if errors else "JSON value did not match anyOf")
    expected = schema.get("type")
    if expected is not None:
        _check_type(instance, expected)
    if "enum" in schema and instance not in schema["enum"]:
        raise ValueError("JSON value is not an allowed enum member")
    if "const" in schema and instance != schema["const"]:
        raise ValueError("JSON value does not match const")
    if isinstance(instance, dict) and (
        expected in {None, "object"}
        or "properties" in schema
        or "required" in schema
        or "additionalProperties" in schema
    ):
        required = schema.get("required") or []
        if not isinstance(required, list):
            raise ValueError("JSON schema required must be a list")
        for key in required:
            if key not in instance:
                raise ValueError(f"Missing required property {key!r}")
        properties = schema.get("properties") or {}
        if not isinstance(properties, dict):
            raise ValueError("JSON schema properties must be an object")
        additional = schema.get("additionalProperties", True)
        for key, value in instance.items():
            nested = properties.get(key)
            if isinstance(nested, dict):
                _validate(value, nested, defs)
            elif additional is False:
                raise ValueError(f"Unexpected property {key!r}")
            elif isinstance(additional, dict):
                _validate(value, additional, defs)
    if isinstance(instance, str):
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if min_length is not None and len(instance) < int(min_length):
            raise ValueError("String is shorter than minLength")
        if max_length is not None and len(instance) > int(max_length):
            raise ValueError("String is longer than maxLength")


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    prefix = None
    if ref.startswith("#/$defs/"):
        prefix = "#/$defs/"
    elif ref.startswith("#/definitions/"):
        prefix = "#/definitions/"
    if prefix is None:
        raise ValueError(f"Unsupported JSON schema ref: {ref}")
    resolved = defs.get(ref[len(prefix) :])
    if not isinstance(resolved, dict):
        raise ValueError(f"Unresolved JSON schema ref: {ref}")
    merged = dict(resolved)
    for key, value in schema.items():
        if key != "$ref":
            merged[key] = value
    return merged


def _check_type(instance: object, expected: object) -> None:
    if isinstance(expected, list):
        errors: list[str] = []
        for option in expected:
            try:
                _check_type(instance, option)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError(errors[-1] if errors else "JSON value had the wrong type")
    if expected == "null":
        if instance is not None:
            raise ValueError("Expected null")
        return
    if expected == "boolean":
        if not isinstance(instance, bool):
            raise ValueError("Expected boolean")
        return
    if expected == "string":
        if not isinstance(instance, str):
            raise ValueError("Expected string")
        return
    if expected == "integer":
        if isinstance(instance, bool) or not isinstance(instance, int):
            raise ValueError("Expected integer")
        return
    if expected == "number":
        if isinstance(instance, bool) or not isinstance(instance, (int, float)):
            raise ValueError("Expected number")
        return
    if expected == "object":
        if not isinstance(instance, dict):
            raise ValueError("Expected object")
        return
    if expected == "array":
        if not isinstance(instance, list):
            raise ValueError("Expected array")
        return
    raise ValueError(f"Unsupported JSON schema type {expected!r}")


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GpuWorkloadPermanentError("Qwen input JSON is missing or invalid") from exc
    if not isinstance(payload, dict):
        raise GpuWorkloadPermanentError("Qwen input JSON must be an object")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GpuWorkloadPermanentError(f"Qwen {field} must be a non-empty string")
    return value.strip()


def _positive_int(value: object, *, default: int, field: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise GpuWorkloadPermanentError(f"Invalid Qwen {field}") from exc
    if parsed <= 0:
        raise GpuWorkloadPermanentError(f"Qwen {field} must be greater than zero")
    return parsed


def _temperature(value: object, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        parsed = float(str(value))
    except (TypeError, ValueError) as exc:
        raise GpuWorkloadPermanentError("Invalid Qwen temperature") from exc
    if parsed < 0 or parsed > 2:
        raise GpuWorkloadPermanentError("Qwen temperature must be between 0 and 2")
    return parsed
