from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Text, func, DateTime, ForeignKey, BigInteger, Integer, Float, UniqueConstraint, \
    CheckConstraint, Index
import sqlalchemy as sa
from sqlalchemy import UUID as SA_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.content_processing.common.types import JobStatus, JobKind


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

    local_path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    media_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )
    # audio, video, document, image

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
