from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Text, func, DateTime, ForeignKey, BigInteger, Integer, Float, UniqueConstraint, \
    CheckConstraint, Index
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    DubbingStatus,
    JobCompletionExpectationKind,
    JobCompletionExpectationStatus,
    JobStatus,
    JobKind,
    MediaAssetRole,
    OutboxEventStatus,
    SubtitleTranslationStatus,
    TranslationBatchStatus,
)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    kind: Mapped[JobKind] =mapped_column(
        sa.Enum(
            JobKind,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        sa.Enum(
            JobStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        default=JobStatus.QUEUED,
        nullable=False,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    callback_required: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.text("true"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class TelegramSource(Base):
    __tablename__ = "telegram_sources"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    job: Mapped[Job] = relationship()

    ingress_message_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    ingress_attachment_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    telegram_file_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    telegram_file_unique_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    attachment_type: Mapped[TelegramAttachmentType] = mapped_column(
        sa.Enum(
            TelegramAttachmentType,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
    )

class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    job: Mapped[Job] = relationship()

    role: Mapped[MediaAssetRole] = mapped_column(
        sa.Enum(
            MediaAssetRole,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=MediaAssetRole.SOURCE,
        server_default=MediaAssetRole.SOURCE.value,
    )

    parent_asset_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("media_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    local_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    media_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    # attachment/content kind: voice, video, video_note, audio, document, photo

    mime_type: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    size_bytes: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "role",
            name="uq_media_assets_job_id_role",
        ),
    )


class JobCompletionExpectation(Base):
    __tablename__ = "job_completion_expectations"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    kind: Mapped[JobCompletionExpectationKind] = mapped_column(
        sa.Enum(
            JobCompletionExpectationKind,
            values_callable=get_enum_values,
            native_enum=False,
            length=64,
        ),
        nullable=False,
        default=JobCompletionExpectationKind.JOB_COMPLETION,
        server_default=JobCompletionExpectationKind.JOB_COMPLETION.value,
    )

    status: Mapped[JobCompletionExpectationStatus] = mapped_column(
        sa.Enum(
            JobCompletionExpectationStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=JobCompletionExpectationStatus.OPEN,
        server_default=JobCompletionExpectationStatus.OPEN.value,
    )

    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    job: Mapped[Job] = relationship()

    __table_args__ = (
        Index(
            "ix_job_completion_expectations_open_due",
            "due_at",
            "created_at",
            postgresql_where=sa.text("status = 'open'"),
        ),
        Index(
            "ix_job_completion_expectations_processing_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'processing'"),
        ),
        Index(
            "ix_job_completion_expectations_resolved",
            "resolved_at",
            postgresql_where=sa.text(
                "status IN ('satisfied', 'timed_out')"
            ),
        ),
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    event_type: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
    )

    status: Mapped[OutboxEventStatus] = mapped_column(
        sa.Enum(
            OutboxEventStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        default=OutboxEventStatus.PENDING,
        server_default=OutboxEventStatus.PENDING.value,
        nullable=False,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=sa.text("0"),
        nullable=False,
    )

    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    job: Mapped[Job] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_outbox_events_idempotency_key",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbox_events_attempt_count_non_negative",
        ),
        Index(
            "ix_outbox_events_pending_available",
            "available_at",
            "created_at",
            postgresql_where=sa.text("status = 'pending'"),
        ),
        Index(
            "ix_outbox_events_processing_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'processing'"),
        ),
    )


class DownloadRequest(Base):
    __tablename__ = "download_requests"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    job: Mapped[Job] = relationship()

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    group_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    agent_message_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    media_ingress_message_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        nullable=False,
        index=True,
    )

    media_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    requested_subtitle_language: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    requested_dub_language: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    requested_language: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    requested_format: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    assistant_text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Telegram message_id of the user request we should reply to on delivery.
    reply_to_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    final_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    delivery_status: Mapped[DownloadDeliveryStatus] = mapped_column(
        sa.Enum(
            DownloadDeliveryStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=DownloadDeliveryStatus.PENDING,
        server_default=DownloadDeliveryStatus.PENDING.value,
    )
    delivery_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    delivery_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_delivery_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "delivery_attempt_count >= 0",
            name="ck_download_requests_delivery_attempt_non_negative",
        ),
    )


class DubbingWorkflow(Base):
    __tablename__ = "dubbing_workflows"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    source_job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_language: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[DubbingStatus] = mapped_column(
        sa.Enum(
            DubbingStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=DubbingStatus.SOURCE_READY,
        server_default=DubbingStatus.SOURCE_READY.value,
        index=True,
    )
    active_gpu_job_id: Mapped[UUID | None] = mapped_column(
        SA_UUID(as_uuid=True), nullable=True, index=True
    )
    cosyvoice_model: Mapped[str] = mapped_column(String(255), nullable=False)
    sam_model: Mapped[str] = mapped_column(String(255), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class DubbingArtifact(Base):
    __tablename__ = "dubbing_artifacts"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workflow_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("dubbing_workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    producer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    artifact_metadata: Mapped[dict[str, object] | None] = mapped_column(
        "metadata", JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "workflow_id", "artifact_type", name="uq_dubbing_artifact_type"
        ),
        CheckConstraint(
            "size_bytes IS NULL OR size_bytes >= 0",
            name="ck_dubbing_artifact_size_non_negative",
        ),
    )


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
        index=True,
    )

    job: Mapped[Job] = relationship()

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    language: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    language_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    duration_ms: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.segment_index",
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    transcript_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("transcripts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    start_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    language: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    language_probability: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    speaker: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    speaker_confidence: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    transcript: Mapped["Transcript"] = relationship(
        back_populates="segments",
    )

    __table_args__ = (
        UniqueConstraint(
            "transcript_id",
            "segment_index",
            name="uq_transcript_segment_index",
        ),
        CheckConstraint(
            "start_ms >= 0",
            name="ck_transcript_segment_start_ms_non_negative",
        ),
        CheckConstraint(
            "end_ms >= start_ms",
            name="ck_transcript_segment_end_after_start",
        ),
        CheckConstraint(
            "segment_index >= 0",
            name="ck_transcript_segment_index_non_negative",
        ),
        Index(
            "ix_transcript_segments_time",
            "transcript_id",
            "start_ms",
            "end_ms",
        ),
    )


class SubtitleTranslation(Base):
    __tablename__ = "subtitle_translations"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    job: Mapped[Job] = relationship()

    source_language: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )

    target_language: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )

    status: Mapped[SubtitleTranslationStatus] = mapped_column(
        sa.Enum(
            SubtitleTranslationStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        default=SubtitleTranslationStatus.PENDING,
        server_default=SubtitleTranslationStatus.PENDING.value,
        nullable=False,
    )

    glossary: Mapped[dict[str, object] | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    model_name: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    batches: Mapped[list["TranslationBatch"]] = relationship(
        back_populates="subtitle_translation",
        cascade="all, delete-orphan",
        order_by="TranslationBatch.batch_index",
    )

    segments: Mapped[list["TranslatedSegment"]] = relationship(
        back_populates="subtitle_translation",
        cascade="all, delete-orphan",
        order_by="TranslatedSegment.segment_index",
    )

    __table_args__ = (
        UniqueConstraint(
            "job_id",
            "target_language",
            name="uq_subtitle_translations_job_language",
        ),
    )


class TranslationBatch(Base):
    __tablename__ = "translation_batches"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    subtitle_translation_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("subtitle_translations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    batch_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    start_segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    status: Mapped[TranslationBatchStatus] = mapped_column(
        sa.Enum(
            TranslationBatchStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        default=TranslationBatchStatus.PENDING,
        server_default=TranslationBatchStatus.PENDING.value,
        nullable=False,
    )

    attempt_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=sa.text("0"),
        nullable=False,
    )

    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    locked_by: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    provider_request_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    input_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    output_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    subtitle_translation: Mapped["SubtitleTranslation"] = relationship(
        back_populates="batches",
    )

    __table_args__ = (
        UniqueConstraint(
            "subtitle_translation_id",
            "batch_index",
            name="uq_translation_batches_translation_index",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_translation_batches_idempotency_key",
        ),
        CheckConstraint(
            "batch_index >= 0",
            name="ck_translation_batches_batch_index_non_negative",
        ),
        CheckConstraint(
            "start_segment_index >= 0",
            name="ck_translation_batches_start_segment_non_negative",
        ),
        CheckConstraint(
            "end_segment_index >= start_segment_index",
            name="ck_translation_batches_end_after_start",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_translation_batches_attempt_count_non_negative",
        ),
        Index(
            "ix_translation_batches_claimable",
            "subtitle_translation_id",
            "status",
            "batch_index",
        ),
        Index(
            "ix_translation_batches_processing_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'processing'"),
        ),
    )


class TranslatedSegment(Base):
    __tablename__ = "translated_segments"

    id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    subtitle_translation_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        ForeignKey("subtitle_translations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    segment_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    start_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    end_ms: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    subtitle_translation: Mapped["SubtitleTranslation"] = relationship(
        back_populates="segments",
    )

    __table_args__ = (
        UniqueConstraint(
            "subtitle_translation_id",
            "segment_index",
            name="uq_translated_segments_translation_index",
        ),
        CheckConstraint(
            "segment_index >= 0",
            name="ck_translated_segments_index_non_negative",
        ),
        CheckConstraint(
            "start_ms >= 0",
            name="ck_translated_segments_start_ms_non_negative",
        ),
        CheckConstraint(
            "end_ms >= start_ms",
            name="ck_translated_segments_end_after_start",
        ),
    )
