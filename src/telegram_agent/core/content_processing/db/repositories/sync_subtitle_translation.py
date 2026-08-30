from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.engine import CursorResult

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.content_processing.common.types import (
    SubtitleTranslationBackend,
    SubtitleTranslationStatus,
    TranslationBatchStatus,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    SubtitleTranslation,
    TranslatedSegment,
    TranslationBatch,
)


@dataclass(frozen=True)
class BatchPlanItem:
    batch_index: int
    start_segment_index: int
    end_segment_index: int


@dataclass(frozen=True)
class TranslatedSegmentInput:
    segment_index: int
    text: str
    start_ms: int
    end_ms: int


class SyncSqlAlchemySubtitleTranslationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_job_language_backend_and_model(
        self,
        *,
        job_id: UUID,
        target_language: str,
        backend: SubtitleTranslationBackend,
        model_name: str,
    ) -> SubtitleTranslation | None:
        return self._session.scalar(
            select(SubtitleTranslation).where(
                SubtitleTranslation.job_id == job_id,
                SubtitleTranslation.target_language == target_language,
                SubtitleTranslation.backend == backend,
                SubtitleTranslation.model_name == model_name,
            )
        )

    def get_by_id(self, translation_id: UUID) -> SubtitleTranslation | None:
        return self._session.scalar(
            select(SubtitleTranslation).where(SubtitleTranslation.id == translation_id)
        )

    def get_by_id_with_batches(
        self,
        translation_id: UUID,
    ) -> SubtitleTranslation | None:
        return self._session.scalar(
            select(SubtitleTranslation)
            .where(SubtitleTranslation.id == translation_id)
            .options(selectinload(SubtitleTranslation.batches))
        )

    def create(
        self,
        *,
        job_id: UUID,
        source_language: str | None,
        target_language: str,
        backend: SubtitleTranslationBackend,
        model_name: str,
    ) -> SubtitleTranslation:
        row = SubtitleTranslation(
            id=uuid4(),
            job_id=job_id,
            source_language=source_language,
            target_language=target_language,
            backend=backend,
            model_name=model_name,
            status=SubtitleTranslationStatus.PENDING,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_status(
        self,
        *,
        translation_id: UUID,
        status: SubtitleTranslationStatus,
        error_message: str | None = None,
    ) -> bool:
        values: dict[str, object] = {
            "status": status,
            "updated_at": func.now(),
        }
        if error_message is not None:
            values["error_message"] = clean_error_message(error_message, max_length=2000)
        elif status != SubtitleTranslationStatus.FAILED:
            values["error_message"] = None
        statement = (
            update(SubtitleTranslation)
            .where(SubtitleTranslation.id == translation_id)
            .values(**values)
            .returning(SubtitleTranslation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def set_glossary(
        self,
        *,
        translation_id: UUID,
        glossary: dict[str, object],
    ) -> bool:
        statement = (
            update(SubtitleTranslation)
            .where(SubtitleTranslation.id == translation_id)
            .values(
                glossary=glossary,
                status=SubtitleTranslationStatus.TRANSLATING,
                error_message=None,
                updated_at=func.now(),
            )
            .returning(SubtitleTranslation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_completed(
        self,
        *,
        translation_id: UUID,
    ) -> bool:
        statement = (
            update(SubtitleTranslation)
            .where(SubtitleTranslation.id == translation_id)
            .values(
                status=SubtitleTranslationStatus.COMPLETED,
                error_message=None,
                completed_at=func.now(),
                updated_at=func.now(),
            )
            .returning(SubtitleTranslation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_failed(
        self,
        *,
        translation_id: UUID,
        error_message: str,
    ) -> bool:
        statement = (
            update(SubtitleTranslation)
            .where(SubtitleTranslation.id == translation_id)
            .values(
                status=SubtitleTranslationStatus.FAILED,
                error_message=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
            .returning(SubtitleTranslation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def list_batches(self, *, translation_id: UUID) -> list[TranslationBatch]:
        return list(
            self._session.scalars(
                select(TranslationBatch)
                .where(TranslationBatch.subtitle_translation_id == translation_id)
                .order_by(TranslationBatch.batch_index)
            ).all()
        )

    def ensure_batches(
        self,
        *,
        translation_id: UUID,
        plans: list[BatchPlanItem],
    ) -> list[TranslationBatch]:
        existing = {
            batch.batch_index: batch for batch in self.list_batches(translation_id=translation_id)
        }
        if existing:
            return [existing[index] for index in sorted(existing)]

        created: list[TranslationBatch] = []
        for plan in plans:
            batch = TranslationBatch(
                id=uuid4(),
                subtitle_translation_id=translation_id,
                batch_index=plan.batch_index,
                start_segment_index=plan.start_segment_index,
                end_segment_index=plan.end_segment_index,
                status=TranslationBatchStatus.PENDING,
                idempotency_key=(
                    f"subtitle-translation-batch:{translation_id}:{plan.batch_index}"
                ),
            )
            self._session.add(batch)
            created.append(batch)
        self._session.flush()
        return created

    def claim_next_batch(
        self,
        *,
        translation_id: UUID,
        lease_owner: str,
        lease_timeout: timedelta,
        max_attempts: int,
    ) -> TranslationBatch | None:
        now = utcnow()
        expired_before = now - lease_timeout
        locked_id_stmt = (
            select(TranslationBatch.id)
            .where(
                TranslationBatch.subtitle_translation_id == translation_id,
                TranslationBatch.attempt_count < max_attempts,
                or_(
                    TranslationBatch.status == TranslationBatchStatus.PENDING,
                    TranslationBatch.status == TranslationBatchStatus.FAILED,
                    and_(
                        TranslationBatch.status == TranslationBatchStatus.PROCESSING,
                        TranslationBatch.locked_at.is_not(None),
                        TranslationBatch.locked_at < expired_before,
                    ),
                ),
            )
            .order_by(TranslationBatch.batch_index)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        batch_id = self._session.scalar(locked_id_stmt)
        if batch_id is None:
            return None

        statement = (
            update(TranslationBatch)
            .where(TranslationBatch.id == batch_id)
            .values(
                status=TranslationBatchStatus.PROCESSING,
                locked_at=now,
                locked_by=lease_owner,
                attempt_count=TranslationBatch.attempt_count + 1,
                updated_at=func.now(),
            )
            .returning(TranslationBatch)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_batch_succeeded(
        self,
        *,
        batch_id: UUID,
        lease_owner: str,
        provider_request_id: str | None,
        input_tokens: int | None,
        output_tokens: int | None,
    ) -> bool:
        statement = (
            update(TranslationBatch)
            .where(
                TranslationBatch.id == batch_id,
                TranslationBatch.status == TranslationBatchStatus.PROCESSING,
                TranslationBatch.locked_by == lease_owner,
            )
            .values(
                status=TranslationBatchStatus.SUCCEEDED,
                locked_at=None,
                locked_by=None,
                last_error=None,
                provider_request_id=provider_request_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                updated_at=func.now(),
            )
            .returning(TranslationBatch.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def mark_batch_failed(
        self,
        *,
        batch_id: UUID,
        lease_owner: str,
        error_message: str,
    ) -> bool:
        statement = (
            update(TranslationBatch)
            .where(
                TranslationBatch.id == batch_id,
                TranslationBatch.status == TranslationBatchStatus.PROCESSING,
                TranslationBatch.locked_by == lease_owner,
            )
            .values(
                status=TranslationBatchStatus.FAILED,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
            .returning(TranslationBatch.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def release_cancelled_batch(
        self,
        *,
        batch_id: UUID,
        lease_owner: str,
    ) -> bool:
        statement = (
            update(TranslationBatch)
            .where(
                TranslationBatch.id == batch_id,
                TranslationBatch.status == TranslationBatchStatus.PROCESSING,
                TranslationBatch.locked_by == lease_owner,
            )
            .values(
                status=TranslationBatchStatus.PENDING,
                locked_at=None,
                locked_by=None,
                attempt_count=func.greatest(TranslationBatch.attempt_count - 1, 0),
                last_error=None,
                updated_at=func.now(),
            )
            .returning(TranslationBatch.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def all_batches_succeeded(self, *, translation_id: UUID) -> bool:
        batches = self.list_batches(translation_id=translation_id)
        if not batches:
            return False
        return all(batch.status == TranslationBatchStatus.SUCCEEDED for batch in batches)

    def has_exhausted_failed_batch(
        self,
        *,
        translation_id: UUID,
        max_attempts: int,
    ) -> bool:
        return (
            self._session.scalar(
                select(TranslationBatch.id)
                .where(
                    TranslationBatch.subtitle_translation_id == translation_id,
                    TranslationBatch.status == TranslationBatchStatus.FAILED,
                    TranslationBatch.attempt_count >= max_attempts,
                )
                .limit(1)
            )
            is not None
        )

    def list_translated_segments(
        self,
        *,
        translation_id: UUID,
    ) -> list[TranslatedSegment]:
        return list(
            self._session.scalars(
                select(TranslatedSegment)
                .where(TranslatedSegment.subtitle_translation_id == translation_id)
                .order_by(TranslatedSegment.segment_index)
            ).all()
        )

    def get_translated_by_indexes(
        self,
        *,
        translation_id: UUID,
        segment_indexes: list[int],
    ) -> list[TranslatedSegment]:
        if not segment_indexes:
            return []
        return list(
            self._session.scalars(
                select(TranslatedSegment)
                .where(
                    TranslatedSegment.subtitle_translation_id == translation_id,
                    TranslatedSegment.segment_index.in_(segment_indexes),
                )
                .order_by(TranslatedSegment.segment_index)
            ).all()
        )

    def replace_batch_segments(
        self,
        *,
        translation_id: UUID,
        segments: list[TranslatedSegmentInput],
    ) -> None:
        if not segments:
            return
        indexes = [segment.segment_index for segment in segments]
        self._session.execute(
            delete(TranslatedSegment).where(
                TranslatedSegment.subtitle_translation_id == translation_id,
                TranslatedSegment.segment_index.in_(indexes),
            )
        )
        for segment in segments:
            self._session.add(
                TranslatedSegment(
                    id=uuid4(),
                    subtitle_translation_id=translation_id,
                    segment_index=segment.segment_index,
                    text=segment.text,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                )
            )
        self._session.flush()

    def requeue_failed_batches(self, *, translation_id: UUID, max_attempts: int) -> int:
        statement = (
            update(TranslationBatch)
            .where(
                TranslationBatch.subtitle_translation_id == translation_id,
                TranslationBatch.status == TranslationBatchStatus.FAILED,
                TranslationBatch.attempt_count < max_attempts,
            )
            .values(
                status=TranslationBatchStatus.PENDING,
                locked_at=None,
                locked_by=None,
                updated_at=func.now(),
            )
        )
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)
