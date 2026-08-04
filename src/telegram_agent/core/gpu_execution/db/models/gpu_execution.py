from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy import UUID as SA_UUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus, GpuOutboxStatus


class GpuJob(Base):
    __tablename__ = "gpu_jobs"

    id: Mapped[UUID] = mapped_column(SA_UUID(as_uuid=True), primary_key=True, default=uuid4)
    workload_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[GpuJobStatus] = mapped_column(
        sa.Enum(
            GpuJobStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=GpuJobStatus.PENDING,
        server_default=GpuJobStatus.PENDING.value,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    input_path: Mapped[str] = mapped_column(Text, nullable=False)
    output_path: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=sa.text("0"))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    process_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancellation_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    outbox_events: Mapped[list["GpuOutboxEvent"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_gpu_jobs_attempt_count_non_negative"),
        CheckConstraint("max_attempts > 0", name="ck_gpu_jobs_max_attempts_positive"),
        CheckConstraint("timeout_seconds > 0", name="ck_gpu_jobs_timeout_positive"),
        Index("ix_gpu_jobs_schedulable", "available_at", "created_at", postgresql_where=sa.text("status IN ('pending', 'retrying')")),
        Index("ix_gpu_jobs_running_lease", "lease_expires_at", postgresql_where=sa.text("status = 'running'")),
    )


class GpuOutboxEvent(Base):
    __tablename__ = "gpu_outbox_events"

    id: Mapped[UUID] = mapped_column(SA_UUID(as_uuid=True), primary_key=True, default=uuid4)
    gpu_job_id: Mapped[UUID] = mapped_column(
        SA_UUID(as_uuid=True),
        sa.ForeignKey("gpu_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delivery_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[GpuOutboxStatus] = mapped_column(
        sa.Enum(
            GpuOutboxStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=GpuOutboxStatus.PENDING,
        server_default=GpuOutboxStatus.PENDING.value,
    )
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    job: Mapped[GpuJob] = relationship(back_populates="outbox_events")

    __table_args__ = (
        UniqueConstraint("delivery_key", name="uq_gpu_outbox_events_delivery_key"),
        Index("ix_gpu_outbox_pending_available", "available_at", "created_at", postgresql_where=sa.text("status = 'pending'")),
        Index("ix_gpu_outbox_processing_lease", "locked_at", postgresql_where=sa.text("status = 'processing'")),
    )


class GpuExecutionSlot(Base):
    """Singleton database lease enforcing one active GPU job globally."""

    __tablename__ = "gpu_execution_slots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gpu_job_id: Mapped[UUID | None] = mapped_column(SA_UUID(as_uuid=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_gpu_execution_slots_singleton"),
    )
