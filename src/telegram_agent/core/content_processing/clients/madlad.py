"""Durable GPU-job adapter for local MADLAD translation."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from telegram_agent.core.common.exceptions import (
    GpuExecutionCanceledError,
    GpuExecutionResponseError,
    GpuExecutionServiceError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.common.gpu_workloads import MADLAD_TRANSLATION_WORKLOAD
from telegram_agent.core.content_processing.clients.gpu_execution_client import (
    GpuExecutionClient,
)
from telegram_agent.core.content_processing.common.language_codes import (
    InvalidLanguageCodeError,
    canonical_madlad_language,
)
from telegram_agent.core.content_processing.common.settings import Settings


class MadladGeneration(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    translations: list[str] = Field(min_length=1)
    source_lang: str | None = None
    target_lang: str
    target_token: str
    model: str
    count: int = Field(ge=1)
    adapter_sha256: str | None = None


class MadladClient:
    """Content-processing adapter over the durable MADLAD GPU workload."""

    def __init__(
        self,
        settings: Settings,
        gpu_client: GpuExecutionClient | None = None,
    ) -> None:
        self._settings = settings
        self._gpu_client = gpu_client or GpuExecutionClient(settings)

    @classmethod
    def from_settings(cls, settings: Settings) -> "MadladClient":
        return cls(settings)

    def translate(
        self,
        texts: list[str],
        *,
        source_lang: str,
        target_lang: str,
        request_id: str,
        heartbeat: Callable[[], None] | None = None,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> MadladGeneration:
        if not texts:
            raise PermanentContentProcessingError(
                "MADLAD translation texts must not be empty"
            )
        if not request_id.strip():
            raise PermanentContentProcessingError(
                "MADLAD translation request_id must not be empty"
            )
        try:
            source = canonical_madlad_language(source_lang)
            target = canonical_madlad_language(target_lang)
        except InvalidLanguageCodeError as exc:
            raise PermanentContentProcessingError(str(exc)) from exc

        storage_root = Path(self._settings.media_storage_root)
        input_path = storage_root / request_id / "gpu_inputs" / "madlad_translation.json"
        output_path = (
            storage_root / request_id / "gpu_results" / "madlad_translation.json"
        )
        _write_json_atomic(
            input_path,
            {
                "texts": texts,
                "source_lang": source,
                "target_lang": target,
            },
        )
        timeout_seconds = self._job_timeout_seconds(len(texts))
        try:
            result_path = self._gpu_client.execute_and_wait(
                workload_type=MADLAD_TRANSLATION_WORKLOAD,
                idempotency_key=f"{MADLAD_TRANSLATION_WORKLOAD}:{request_id}",
                input_path=input_path,
                output_path=output_path,
                parameters={
                    "model": "google/madlad400-3b-mt",
                    "beam_size": self._settings.madlad_beam_size,
                    "max_new_tokens": self._settings.madlad_max_new_tokens,
                    "max_batch_size": self._settings.madlad_client_batch_size,
                },
                timeout_seconds=timeout_seconds,
                max_attempts=min(
                    self._settings.madlad_request_max_attempts,
                    self._settings.gpu_execution_job_max_attempts,
                ),
                heartbeat=heartbeat,
                cancellation_requested=cancellation_requested,
            )
        except GpuExecutionCanceledError:
            raise
        except GpuExecutionResponseError as exc:
            raise PermanentContentProcessingError(str(exc)) from exc
        except GpuExecutionServiceError as exc:
            raise RetryableContentProcessingError(str(exc)) from exc

        try:
            generation = MadladGeneration.model_validate(
                json.loads(result_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeDecodeError, ValueError, ValidationError) as exc:
            raise RetryableContentProcessingError(
                "MADLAD GPU workload returned an invalid translation response"
            ) from exc

        if generation.count != len(texts) or len(generation.translations) != len(texts):
            raise RetryableContentProcessingError(
                "MADLAD returned a different number of translations than requested"
            )
        if any(not isinstance(text, str) for text in generation.translations):
            raise RetryableContentProcessingError(
                "MADLAD returned a non-string translation"
            )
        return generation

    def _job_timeout_seconds(self, text_count: int) -> int:
        batch_size = max(1, self._settings.madlad_client_batch_size)
        mini_batches = max(1, (text_count + batch_size - 1) // batch_size)
        scaled = int(self._settings.madlad_request_timeout_seconds * mini_batches)
        return max(
            1,
            min(scaled, self._settings.gpu_execution_job_max_timeout_seconds),
        )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)
