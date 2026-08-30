from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable
from uuid import UUID, uuid4

from telegram_agent.core.common.exceptions import (
    GpuExecutionCanceledError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
    SecondaryTaskCancelledError,
)
from telegram_agent.core.common.spoken_text import sanitize_spoken_text
from telegram_agent.core.content_processing.clients.llm_gateway import LlmGatewayClient
from telegram_agent.core.content_processing.clients.madlad import (
    MadladClient,
    MadladGeneration,
)
from telegram_agent.core.content_processing.common.language_codes import (
    canonical_madlad_language,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import SubtitleTranslationStatus
from telegram_agent.core.content_processing.db.models.content_processing import (
    SubtitleTranslation,
)
from telegram_agent.core.content_processing.db.repositories.sync_subtitle_translation import (
    TranslatedSegmentInput,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitleSegment,
)
from telegram_agent.core.content_processing.services.subtitle_translation_helpers import (
    SourceSegmentView,
    empty_glossary,
    languages_match,
    normalize_language,
    plan_translation_batches,
)

logger = logging.getLogger(__name__)


class SyncSubtitleTranslationService:
    """Resumable subtitle translation via MADLAD GPU jobs."""

    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
        llm_gateway_client: LlmGatewayClient | None,
        madlad_client: MadladClient | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._llm_gateway_client = llm_gateway_client
        self._madlad_client = madlad_client

    @classmethod
    def from_settings(
        cls,
        *,
        llm_gateway_client: LlmGatewayClient | None = None,
        madlad_client: MadladClient | None = None,
    ) -> "SyncSubtitleTranslationService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        if madlad_client is None and settings.subtitle_translation_enabled:
            madlad_client = MadladClient.from_settings(settings)
        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
            llm_gateway_client=llm_gateway_client,
            madlad_client=madlad_client,
        )

    def ensure_translated(
        self,
        *,
        source_job_id: UUID,
        target_language: str | None,
        overwrite: bool = False,
        cancellation_requested: Callable[[], bool] | None = None,
    ) -> list[SubtitleSegment]:
        self._raise_if_cancelled(cancellation_requested)
        if overwrite:
            raise PermanentContentProcessingError(
                "Subtitle translation overwrite is not supported yet"
            )

        source_segments = self._load_source_segments(source_job_id)
        if not source_segments:
            raise PermanentContentProcessingError(
                "Cannot translate subtitles without transcript segments"
            )

        source_language = self._load_source_language(source_job_id)
        target_norm = normalize_language(target_language)

        if self._should_skip_translation(
            source_language=source_language,
            target_language=target_norm,
        ):
            return self._as_subtitle_segments(source_segments)

        if target_norm is None:
            return self._as_subtitle_segments(source_segments)

        translation = self._get_or_create_translation(
            source_job_id=source_job_id,
            source_language=source_language,
            target_language=target_norm,
        )

        if translation.status == SubtitleTranslationStatus.COMPLETED:
            return self._load_completed_segments(translation.id)

        if translation.status == SubtitleTranslationStatus.FAILED:
            self._prepare_failed_for_resume(translation.id)

        if translation.glossary is None:
            self._set_empty_glossary(translation.id)

        self._ensure_batches_planned(
            translation_id=translation.id,
            source_segments=source_segments,
        )
        self._translate_remaining_batches(
            translation_id=translation.id,
            source_language=source_language,
            target_language=target_norm,
            source_segments=source_segments,
            cancellation_requested=cancellation_requested,
        )
        self._raise_if_cancelled(cancellation_requested)
        return self._load_completed_segments(translation.id)

    def _should_skip_translation(
        self,
        *,
        source_language: str | None,
        target_language: str | None,
    ) -> bool:
        if not self._settings.subtitle_translation_enabled:
            return True
        if target_language is None:
            return True
        return languages_match(source_language, target_language)

    def _load_source_language(self, source_job_id: UUID) -> str | None:
        with self._uow_factory() as uow:
            transcript = uow.transcripts.get_by_job_id(source_job_id)
            if transcript is None:
                raise PermanentContentProcessingError(
                    "Source transcript is missing for subtitle translation"
                )
            return transcript.language

    def _load_source_segments(self, source_job_id: UUID) -> list[SourceSegmentView]:
        with self._uow_factory() as uow:
            transcript = uow.transcripts.get_by_job_id_with_segments(source_job_id)
            if transcript is None:
                raise PermanentContentProcessingError(
                    "Source transcript is missing for subtitle translation"
                )
            return [
                SourceSegmentView(
                    segment_index=segment.segment_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                )
                for segment in transcript.segments
                if (segment.text or "").strip()
            ]

    def _get_or_create_translation(
        self,
        *,
        source_job_id: UUID,
        source_language: str | None,
        target_language: str,
    ) -> SubtitleTranslation:
        with self._uow_factory() as uow:
            existing = uow.subtitle_translations.get_by_job_and_language(
                job_id=source_job_id,
                target_language=target_language,
            )
            if existing is not None:
                return SubtitleTranslation(
                    id=existing.id,
                    job_id=existing.job_id,
                    source_language=existing.source_language,
                    target_language=existing.target_language,
                    status=existing.status,
                    glossary=existing.glossary,
                    model_name=existing.model_name,
                    error_message=existing.error_message,
                    completed_at=existing.completed_at,
                )
            created = uow.subtitle_translations.create(
                job_id=source_job_id,
                source_language=source_language,
                target_language=target_language,
            )
            return SubtitleTranslation(
                id=created.id,
                job_id=created.job_id,
                source_language=created.source_language,
                target_language=created.target_language,
                status=created.status,
                glossary=created.glossary,
                model_name=created.model_name,
                error_message=created.error_message,
                completed_at=created.completed_at,
            )

    def _prepare_failed_for_resume(self, translation_id: UUID) -> None:
        with self._uow_factory() as uow:
            max_attempts = self._settings.subtitle_translation_max_batch_attempts
            if uow.subtitle_translations.has_exhausted_failed_batch(
                translation_id=translation_id,
                max_attempts=max_attempts,
            ):
                # Allow resume on a fresh ensure call by requeueing only non-exhausted.
                pass
            uow.subtitle_translations.requeue_failed_batches(
                translation_id=translation_id,
                max_attempts=max_attempts,
            )
            uow.subtitle_translations.set_status(
                translation_id=translation_id,
                status=SubtitleTranslationStatus.TRANSLATING,
            )

    def _require_madlad_client(self) -> MadladClient:
        if self._madlad_client is None:
            self._madlad_client = MadladClient.from_settings(self._settings)
        return self._madlad_client

    def _set_empty_glossary(self, translation_id: UUID) -> None:
        with self._uow_factory() as uow:
            uow.subtitle_translations.set_glossary(
                translation_id=translation_id,
                glossary=empty_glossary(),
            )

    def _ensure_batches_planned(
        self,
        *,
        translation_id: UUID,
        source_segments: list[SourceSegmentView],
    ) -> None:
        plans = plan_translation_batches(
            source_segments,
            max_source_tokens=10**9,
            max_segments=max(len(source_segments), 1),
        )
        with self._uow_factory() as uow:
            uow.subtitle_translations.ensure_batches(
                translation_id=translation_id,
                plans=plans,
            )
            uow.subtitle_translations.set_status(
                translation_id=translation_id,
                status=SubtitleTranslationStatus.TRANSLATING,
            )

    def _translate_remaining_batches(
        self,
        *,
        translation_id: UUID,
        source_language: str | None,
        target_language: str,
        source_segments: list[SourceSegmentView],
        cancellation_requested: Callable[[], bool] | None,
    ) -> None:
        by_index = {segment.segment_index: segment for segment in source_segments}
        ordered_indexes = [segment.segment_index for segment in source_segments]
        madlad_client = self._require_madlad_client()
        lease_owner = f"subtitle-translation:{uuid4()}"
        lease_timeout = timedelta(
            seconds=self._settings.subtitle_translation_batch_lease_seconds
        )
        max_attempts = self._settings.subtitle_translation_max_batch_attempts
        last_model: str | None = None

        while True:
            self._raise_if_cancelled(cancellation_requested)
            with self._uow_factory() as uow:
                if uow.subtitle_translations.all_batches_succeeded(
                    translation_id=translation_id
                ):
                    break
                if uow.subtitle_translations.has_exhausted_failed_batch(
                    translation_id=translation_id,
                    max_attempts=max_attempts,
                ):
                    uow.subtitle_translations.mark_failed(
                        translation_id=translation_id,
                        error_message="Subtitle translation batch attempts exhausted",
                    )
                    raise PermanentContentProcessingError(
                        "Subtitle translation batch attempts exhausted"
                    )
                batch = uow.subtitle_translations.claim_next_batch(
                    translation_id=translation_id,
                    lease_owner=lease_owner,
                    lease_timeout=lease_timeout,
                    max_attempts=max_attempts,
                )
                if batch is None:
                    # Another worker may hold a non-stale processing lease.
                    raise RetryableContentProcessingError(
                        "Subtitle translation batch is locked; waiting to retry"
                    )
                batch_id = batch.id
                batch_attempt = batch.attempt_count
                start_index = batch.start_segment_index
                end_index = batch.end_segment_index
            batch_indexes = [
                index
                for index in ordered_indexes
                if start_index <= index <= end_index
            ]
            if not batch_indexes:
                with self._uow_factory() as uow:
                    uow.subtitle_translations.mark_batch_failed(
                        batch_id=batch_id,
                        lease_owner=lease_owner,
                        error_message="Translation batch range contains no source segments",
                    )
                raise PermanentContentProcessingError(
                    "Translation batch range contains no source segments"
                )

            try:
                self._raise_if_cancelled(cancellation_requested)
                generation = self._translate_with_madlad(
                    client=madlad_client,
                    source_language=source_language,
                    target_language=target_language,
                    batch_indexes=batch_indexes,
                    by_index=by_index,
                    request_id=(
                        f"{translation_id}/{batch_id}/attempt-{batch_attempt}"
                    ),
                    cancellation_requested=cancellation_requested,
                )
                self._raise_if_cancelled(cancellation_requested)
                validated = list(zip(batch_indexes, generation.translations))
                provider_request_id = None
                input_tokens = None
                output_tokens = None
            except (SecondaryTaskCancelledError, GpuExecutionCanceledError):
                with self._uow_factory() as uow:
                    uow.subtitle_translations.release_cancelled_batch(
                        batch_id=batch_id,
                        lease_owner=lease_owner,
                    )
                raise SecondaryTaskCancelledError(
                    "Subtitle translation was cancelled"
                )
            except RetryableContentProcessingError as exc:
                with self._uow_factory() as uow:
                    uow.subtitle_translations.mark_batch_failed(
                        batch_id=batch_id,
                        lease_owner=lease_owner,
                        error_message=str(exc),
                    )
                raise
            except PermanentContentProcessingError as exc:
                with self._uow_factory() as uow:
                    uow.subtitle_translations.mark_batch_failed(
                        batch_id=batch_id,
                        lease_owner=lease_owner,
                        error_message=str(exc),
                    )
                    uow.subtitle_translations.mark_failed(
                        translation_id=translation_id,
                        error_message=str(exc),
                    )
                raise

            segment_inputs = [
                TranslatedSegmentInput(
                    segment_index=index,
                    text=text,
                    start_ms=by_index[index].start_ms,
                    end_ms=by_index[index].end_ms,
                )
                for index, text in validated
            ]
            last_model = generation.model

            self._raise_if_cancelled(cancellation_requested)
            with self._uow_factory() as uow:
                uow.subtitle_translations.replace_batch_segments(
                    translation_id=translation_id,
                    segments=segment_inputs,
                )
                if not uow.subtitle_translations.mark_batch_succeeded(
                    batch_id=batch_id,
                    lease_owner=lease_owner,
                    provider_request_id=provider_request_id,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ):
                    raise RetryableContentProcessingError(
                        "Failed to mark translation batch succeeded under lease"
                    )

            logger.info(
                "Completed subtitle translation batch",
                extra={
                    "translation_id": str(translation_id),
                    "batch_id": str(batch_id),
                    "segment_count": len(segment_inputs),
                },
            )

        with self._uow_factory() as uow:
            translated = uow.subtitle_translations.list_translated_segments(
                translation_id=translation_id
            )
            expected = {segment.segment_index for segment in source_segments}
            actual = {row.segment_index for row in translated}
            if actual != expected:
                uow.subtitle_translations.mark_failed(
                    translation_id=translation_id,
                    error_message="Translated segment coverage incomplete after all batches",
                )
                raise PermanentContentProcessingError(
                    "Translated segment coverage incomplete after all batches"
                )
            uow.subtitle_translations.mark_completed(
                translation_id=translation_id,
                model_name=last_model,
            )

    def _translate_with_madlad(
        self,
        *,
        client: MadladClient,
        source_language: str | None,
        target_language: str,
        batch_indexes: list[int],
        by_index: dict[int, SourceSegmentView],
        request_id: str,
        cancellation_requested: Callable[[], bool] | None,
    ) -> MadladGeneration:
        if source_language is None:
            raise PermanentContentProcessingError(
                "Source language is required for local MADLAD translation"
            )
        source_code = canonical_madlad_language(source_language)
        target_code = canonical_madlad_language(target_language)
        generation = client.translate(
            [by_index[index].text for index in batch_indexes],
            source_lang=source_code,
            target_lang=target_code,
            request_id=request_id,
            cancellation_requested=cancellation_requested,
        )
        cleaned = [
            sanitize_spoken_text((text or "").strip()).strip()
            for text in generation.translations
        ]
        if len(cleaned) != len(batch_indexes) or any(not text for text in cleaned):
            raise RetryableContentProcessingError(
                "MADLAD returned empty or incomplete subtitle translations"
            )
        logger.info(
            "Completed local MADLAD subtitle translation",
            extra={
                "segment_count": len(cleaned),
                "source_language": source_code,
                "target_language": target_code,
                "adapter_sha256": generation.adapter_sha256,
            },
        )
        return MadladGeneration(
            translations=cleaned,
            source_lang=generation.source_lang,
            target_lang=generation.target_lang,
            target_token=generation.target_token,
            model=generation.model,
            count=len(cleaned),
            adapter_sha256=generation.adapter_sha256,
        )

    @staticmethod
    def _raise_if_cancelled(
        cancellation_requested: Callable[[], bool] | None,
    ) -> None:
        if cancellation_requested is not None and cancellation_requested():
            raise SecondaryTaskCancelledError("Secondary task was cancelled")

    def _load_completed_segments(self, translation_id: UUID) -> list[SubtitleSegment]:
        with self._uow_factory() as uow:
            rows = uow.subtitle_translations.list_translated_segments(
                translation_id=translation_id
            )
            if not rows:
                raise PermanentContentProcessingError(
                    "Completed subtitle translation has no translated segments"
                )
            return [
                SubtitleSegment(
                    start_ms=row.start_ms,
                    end_ms=row.end_ms,
                    text=row.text,
                )
                for row in rows
            ]

    @staticmethod
    def _as_subtitle_segments(
        source_segments: list[SourceSegmentView],
    ) -> list[SubtitleSegment]:
        return [
            SubtitleSegment(
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
            )
            for segment in source_segments
        ]
