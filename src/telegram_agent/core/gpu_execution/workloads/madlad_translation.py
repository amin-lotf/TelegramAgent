"""GPU workload: load 4-bit MADLAD, translate a JSON batch, then exit."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from telegram_agent.core.gpu_execution.workloads.madlad_engine import MadladEngine
from telegram_agent.core.gpu_execution.workloads.madlad_languages import (
    UnknownLanguageError,
    parse_lora_languages,
    target_language_token,
)
from telegram_agent.core.gpu_execution.workloads.protocol import (
    GpuWorkloadHandler,
    GpuWorkloadPermanentError,
    GpuWorkloadRetryableError,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "google/madlad400-3b-mt"
_DEFAULT_ADAPTER_DIR = "/adapters"
_DEFAULT_LOAD_LORA_FOR = "fa"
_DEFAULT_MAX_BATCH_SIZE = 8
_DEFAULT_BEAM_SIZE = 4
_DEFAULT_MAX_NEW_TOKENS = 256
_DEFAULT_MAX_SOURCE_LENGTH = 256
_DEFAULT_MAX_INPUT_CHARS = 4000


class MadladTranslationWorkload:
    def execute(
        self,
        *,
        input_path: Path,
        output_path: Path,
        parameters: dict[str, object],
    ) -> None:
        payload = _load_object(input_path)
        texts = payload.get("texts")
        if not isinstance(texts, list) or not texts:
            raise GpuWorkloadPermanentError("MADLAD input texts must be a non-empty list")
        if any(not isinstance(text, str) for text in texts):
            raise GpuWorkloadPermanentError("MADLAD input texts must all be strings")

        source_lang = _optional_string(payload.get("source_lang"))
        target_lang = _required_string(payload.get("target_lang"), field="target_lang")
        model_id = str(
            parameters.get("model")
            or os.getenv("MADLAD_MODEL_ID", _DEFAULT_MODEL_ID)
        ).strip()
        installed_model = os.getenv("MADLAD_MODEL_ID", _DEFAULT_MODEL_ID).strip()
        if model_id != installed_model:
            raise GpuWorkloadPermanentError(
                f"MADLAD model {model_id!r} is not installed in this worker"
            )

        max_batch_size = _positive_int(
            parameters.get("max_batch_size"),
            default=_DEFAULT_MAX_BATCH_SIZE,
            field="max_batch_size",
        )
        beam_size = _positive_int(
            parameters.get("beam_size"),
            default=_DEFAULT_BEAM_SIZE,
            field="beam_size",
        )
        max_new_tokens = _positive_int(
            parameters.get("max_new_tokens"),
            default=_DEFAULT_MAX_NEW_TOKENS,
            field="max_new_tokens",
        )
        engine = _build_engine(
            model_id=model_id,
            max_batch_size=max_batch_size,
            beam_size=beam_size,
            max_new_tokens=max_new_tokens,
        )
        translations: list[str] = []
        resolved_target = target_lang
        adapter_sha256: str | None = None
        try:
            engine.load()
            try:
                resolved_target = engine.resolve_lang(target_lang)
            except UnknownLanguageError as exc:
                raise GpuWorkloadPermanentError(str(exc)) from exc
            for start in range(0, len(texts), engine.max_batch_size):
                chunk = texts[start : start + engine.max_batch_size]
                try:
                    translations.extend(
                        engine.translate_batch(
                            chunk,
                            source_lang=source_lang,
                            target_lang=target_lang,
                            beam_size=beam_size,
                            max_new_tokens=max_new_tokens,
                        )
                    )
                except UnknownLanguageError as exc:
                    raise GpuWorkloadPermanentError(str(exc)) from exc
                except ValueError as exc:
                    raise GpuWorkloadPermanentError(str(exc)) from exc
            adapter_sha256 = engine.adapter_sha256
        except GpuWorkloadPermanentError:
            raise
        except RuntimeError as exc:
            message = str(exc)
            if "CUDA" in message or "cuda" in message.lower():
                raise GpuWorkloadRetryableError(message) from exc
            raise GpuWorkloadPermanentError(message) from exc
        finally:
            engine._model = None
            engine._base_model = None
            engine._tokenizer = None

        if len(translations) != len(texts):
            raise GpuWorkloadRetryableError(
                "MADLAD generator returned an invalid result count"
            )
        _write_json_atomic(
            output_path,
            {
                "translations": translations,
                "source_lang": source_lang,
                "target_lang": resolved_target,
                "target_token": target_language_token(resolved_target),
                "model": model_id,
                "count": len(translations),
                "adapter_sha256": adapter_sha256,
            },
        )
        logger.info(
            "MADLAD translation complete count=%s target=%s",
            len(translations),
            resolved_target,
        )


def create_handler() -> GpuWorkloadHandler:
    return MadladTranslationWorkload()


def _build_engine(
    *,
    model_id: str,
    max_batch_size: int,
    beam_size: int,
    max_new_tokens: int,
) -> MadladEngine:
    adapter_dir = os.getenv("MADLAD_ADAPTER_DIR", _DEFAULT_ADAPTER_DIR).strip()
    lora_languages = parse_lora_languages(
        os.getenv("MADLAD_LOAD_LORA_FOR", _DEFAULT_LOAD_LORA_FOR)
    )
    device = os.getenv("MADLAD_DEVICE", "auto").strip() or "auto"
    max_source_length = _positive_int(
        os.getenv("MADLAD_MAX_SOURCE_LENGTH"),
        default=_DEFAULT_MAX_SOURCE_LENGTH,
        field="MADLAD_MAX_SOURCE_LENGTH",
    )
    max_input_chars = _positive_int(
        os.getenv("MADLAD_MAX_INPUT_CHARS"),
        default=_DEFAULT_MAX_INPUT_CHARS,
        field="MADLAD_MAX_INPUT_CHARS",
    )
    return MadladEngine(
        model_id=model_id,
        adapter_dir=adapter_dir,
        lora_languages=lora_languages,
        device=device,
        max_batch_size=max_batch_size,
        default_beam_size=beam_size,
        default_max_new_tokens=max_new_tokens,
        max_source_length=max_source_length,
        max_input_chars=max_input_chars,
        hf_token=os.environ.get("HF_TOKEN") or None,
    )


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GpuWorkloadPermanentError("MADLAD input JSON is missing or invalid") from exc
    if not isinstance(payload, dict):
        raise GpuWorkloadPermanentError("MADLAD input JSON must be an object")
    return payload


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _required_string(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GpuWorkloadPermanentError(f"MADLAD {field} must be a non-empty string")
    return value.strip()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise GpuWorkloadPermanentError("MADLAD source_lang must be a string when provided")
    stripped = value.strip()
    return stripped or None


def _positive_int(value: object, *, default: int, field: str) -> int:
    if value is None or value == "":
        return default
    try:
        parsed = int(str(value))
    except (TypeError, ValueError) as exc:
        raise GpuWorkloadPermanentError(f"Invalid MADLAD {field}") from exc
    if parsed <= 0:
        raise GpuWorkloadPermanentError(f"MADLAD {field} must be greater than zero")
    return parsed
