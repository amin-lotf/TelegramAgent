from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable
from uuid import UUID, uuid4

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.content_processing.clients.llm_gateway import LlmGatewayClient
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
from telegram_agent.core.content_processing.prompts.glossary_extraction import (
    build_glossary_extraction_prompts,
)
from telegram_agent.core.content_processing.prompts.subtitle_translation import (
    build_subtitle_translation_prompts,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitleSegment,
)
from telegram_agent.core.content_processing.services.subtitle_translation_helpers import (
    SourceSegmentView,
    build_glossary_windows,
    consolidate_glossaries,
    context_pair_payload,
    empty_glossary,
    languages_match,
    normalize_language,
    plan_translation_batches,
    segment_payload,
    validate_batch_translations,
)

logger = logging.getLogger(__name__)


class SyncSubtitleTranslationService:
    """Multi-stage, resumable subtitle translation (glossary then batches)."""

    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
        llm_gateway_client: LlmGatewayClient | None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._llm_gateway_client = llm_gateway_client

    @classmethod
    def from_settings(
        cls,
        *,
        llm_gateway_client: LlmGatewayClient | None = None,
    ) -> "SyncSubtitleTranslationService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        if llm_gateway_client is None and settings.subtitle_translation_enabled:
            if settings.llm_gateway_service_token is None:
                # Lazily fail only when translation is actually required.
                llm_gateway_client = None
            else:
                llm_gateway_client = LlmGatewayClient(
                    base_url=settings.llm_gateway_base_url,
                    token=settings.llm_gateway_service_token,
                    timeout_seconds=settings.llm_gateway_request_timeout_seconds,
                )
        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
            llm_gateway_client=llm_gateway_client,
        )

    def ensure_translated(
        self,
        *,
        source_job_id: UUID,
        target_language: str | None,
        overwrite: bool = False,
    ) -> list[SubtitleSegment]:
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
            self._build_glossary(
                translation_id=translation.id,
                source_language=source_language,
                target_language=target_norm,
                source_segments=source_segments,
            )

        self._ensure_batches_planned(
            translation_id=translation.id,
            source_segments=source_segments,
        )
        self._translate_remaining_batches(
            translation_id=translation.id,
            source_language=source_language,
            target_language=target_norm,
            source_segments=source_segments,
        )
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

    def _require_llm_client(self) -> LlmGatewayClient:
        if self._llm_gateway_client is not None:
            return self._llm_gateway_client
        if self._settings.llm_gateway_service_token is None:
            raise PermanentContentProcessingError(
                "LLM_GATEWAY_SERVICE_TOKEN must be configured for subtitle translation"
            )
        self._llm_gateway_client = LlmGatewayClient(
            base_url=self._settings.llm_gateway_base_url,
            token=self._settings.llm_gateway_service_token,
            timeout_seconds=self._settings.llm_gateway_request_timeout_seconds,
        )
        return self._llm_gateway_client

    def _build_glossary(
        self,
        *,
        translation_id: UUID,
        source_language: str | None,
        target_language: str,
        source_segments: list[SourceSegmentView],
    ) -> None:
        with self._uow_factory() as uow:
            uow.subtitle_translations.set_status(
                translation_id=translation_id,
                status=SubtitleTranslationStatus.BUILDING_GLOSSARY,
            )

        windows = build_glossary_windows(
            source_segments,
            window_token_budget=self._settings.subtitle_glossary_window_token_budget,
            max_windows=self._settings.subtitle_glossary_max_windows,
            max_windows_long=self._settings.subtitle_glossary_max_windows_long,
            overlap_ratio=self._settings.subtitle_glossary_overlap_ratio,
        )
        client = self._require_llm_client()
        partials: list[dict] = []
        last_model: str | None = None

        try:
            for window_index, window in enumerate(windows):
                prompts = build_glossary_extraction_prompts(
                    source_language=source_language,
                    target_language=target_language,
                    window_segments=[segment_payload(segment) for segment in window],
                    window_index=window_index,
                    window_count=len(windows),
                )
                generation = client.extract_glossary(
                    system_prompt=prompts.system_prompt,
                    user_prompt=prompts.user_prompt,
                )
                partials.append(generation.output)
                last_model = generation.model
        except RetryableContentProcessingError:
            raise
        except PermanentContentProcessingError as exc:
            with self._uow_factory() as uow:
                uow.subtitle_translations.mark_failed(
                    translation_id=translation_id,
                    error_message=str(exc),
                )
            raise

        glossary = (
            consolidate_glossaries(
                partials,
                max_entries=self._settings.subtitle_glossary_max_entries,
            )
            if partials
            else empty_glossary()
        )

        with self._uow_factory() as uow:
            uow.subtitle_translations.set_glossary(
                translation_id=translation_id,
                glossary=glossary,
            )
            if last_model:
                uow.subtitle_translations.set_model_name(
                    translation_id=translation_id,
                    model_name=last_model,
                )

        logger.info(
            "Built subtitle glossary",
            extra={
                "translation_id": str(translation_id),
                "window_count": len(windows),
                "entry_count": len(glossary.get("entries") or []),
            },
        )

    def _ensure_batches_planned(
        self,
        *,
        translation_id: UUID,
        source_segments: list[SourceSegmentView],
    ) -> None:
        plans = plan_translation_batches(
            source_segments,
            max_source_tokens=self._settings.subtitle_translation_max_source_tokens,
            max_segments=self._settings.subtitle_translation_max_segments_per_batch,
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
    ) -> None:
        by_index = {segment.segment_index: segment for segment in source_segments}
        ordered_indexes = [segment.segment_index for segment in source_segments]
        client = self._require_llm_client()
        lease_owner = f"subtitle-translation:{uuid4()}"
        lease_timeout = timedelta(
            seconds=self._settings.subtitle_translation_batch_lease_seconds
        )
        max_attempts = self._settings.subtitle_translation_max_batch_attempts
        last_model: str | None = None

        while True:
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
                start_index = batch.start_segment_index
                end_index = batch.end_segment_index
                translation = uow.subtitle_translations.get_by_id(translation_id)
                if translation is None or translation.glossary is None:
                    raise PermanentContentProcessingError(
                        "Subtitle translation glossary is missing before batch translate"
                    )
                glossary_payload = dict(translation.glossary)

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

            first_pos = ordered_indexes.index(batch_indexes[0])
            last_pos = ordered_indexes.index(batch_indexes[-1])
            prev_start = max(0, first_pos - self._settings.subtitle_translation_previous_context)
            prev_indexes = ordered_indexes[prev_start:first_pos]
            upcoming_indexes = ordered_indexes[
                last_pos + 1 : last_pos + 1 + self._settings.subtitle_translation_lookahead
            ]

            with self._uow_factory() as uow:
                prev_translated = {
                    row.segment_index: row.text
                    for row in uow.subtitle_translations.get_translated_by_indexes(
                        translation_id=translation_id,
                        segment_indexes=prev_indexes,
                    )
                }

            previous_context = []
            for index in prev_indexes:
                translated_text = prev_translated.get(index)
                if translated_text is None:
                    continue
                previous_context.append(
                    context_pair_payload(
                        source=by_index[index],
                        translated_text=translated_text,
                    )
                )

            translate_segments = [
                segment_payload(by_index[index]) for index in batch_indexes
            ]
            upcoming_segments = [
                segment_payload(by_index[index]) for index in upcoming_indexes
            ]

            prompts = build_subtitle_translation_prompts(
                source_language=source_language,
                target_language=target_language,
                glossary=glossary_payload,
                previous_context=previous_context,
                translate_segments=translate_segments,
                upcoming_segments=upcoming_segments,
            )

            try:
                generation = client.translate_subtitle_batch(
                    system_prompt=prompts.system_prompt,
                    user_prompt=prompts.user_prompt,
                )
                validated = validate_batch_translations(
                    expected_indexes=set(batch_indexes),
                    output=generation.output,
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

            with self._uow_factory() as uow:
                uow.subtitle_translations.replace_batch_segments(
                    translation_id=translation_id,
                    segments=segment_inputs,
                )
                if not uow.subtitle_translations.mark_batch_succeeded(
                    batch_id=batch_id,
                    lease_owner=lease_owner,
                    provider_request_id=generation.provider_request_id,
                    input_tokens=generation.usage.input_tokens,
                    output_tokens=generation.usage.output_tokens,
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
