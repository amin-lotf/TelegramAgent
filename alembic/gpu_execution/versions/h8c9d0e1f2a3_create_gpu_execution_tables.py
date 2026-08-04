"""create GPU execution tables

Revision ID: h8c9d0e1f2a3
Revises:
Create Date: 2026-08-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "h8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "gpu_execution_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gpu_job_id", sa.UUID(), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_gpu_execution_slots_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO gpu_execution_slots (id) VALUES (1)")
    op.create_table(
        "gpu_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workload_type", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("input_path", sa.Text(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("process_id", sa.Integer(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_kind", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_gpu_jobs_attempt_count_non_negative"),
        sa.CheckConstraint("max_attempts > 0", name="ck_gpu_jobs_max_attempts_positive"),
        sa.CheckConstraint("timeout_seconds > 0", name="ck_gpu_jobs_timeout_positive"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_gpu_jobs_workload_type", "gpu_jobs", ["workload_type"])
    op.create_index(
        "ix_gpu_jobs_schedulable",
        "gpu_jobs",
        ["available_at", "created_at"],
        postgresql_where=sa.text("status IN ('pending', 'retrying')"),
    )
    op.create_index(
        "ix_gpu_jobs_running_lease",
        "gpu_jobs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_table(
        "gpu_outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("gpu_job_id", sa.UUID(), nullable=False),
        sa.Column("delivery_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["gpu_job_id"], ["gpu_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("delivery_key", name="uq_gpu_outbox_events_delivery_key"),
    )
    op.create_index("ix_gpu_outbox_events_gpu_job_id", "gpu_outbox_events", ["gpu_job_id"])
    op.create_index(
        "ix_gpu_outbox_pending_available",
        "gpu_outbox_events",
        ["available_at", "created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_gpu_outbox_processing_lease",
        "gpu_outbox_events",
        ["locked_at"],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index("ix_gpu_outbox_processing_lease", table_name="gpu_outbox_events")
    op.drop_index("ix_gpu_outbox_pending_available", table_name="gpu_outbox_events")
    op.drop_index("ix_gpu_outbox_events_gpu_job_id", table_name="gpu_outbox_events")
    op.drop_table("gpu_outbox_events")
    op.drop_index("ix_gpu_jobs_running_lease", table_name="gpu_jobs")
    op.drop_index("ix_gpu_jobs_schedulable", table_name="gpu_jobs")
    op.drop_index("ix_gpu_jobs_workload_type", table_name="gpu_jobs")
    op.drop_table("gpu_jobs")
    op.drop_table("gpu_execution_slots")
