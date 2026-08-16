"""Add durable dubbing workflows and download delivery state.

Revision ID: i9d0e1f2a3b4
Revises: g7b8c9d0e1f2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "i9d0e1f2a3b4"
down_revision: Union[str, Sequence[str], None] = "g7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column("delivery_status", sa.String(length=32), server_default="pending", nullable=False),
    )
    op.add_column(
        "download_requests",
        sa.Column("delivery_attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column("download_requests", sa.Column("delivery_error", sa.Text(), nullable=True))
    op.add_column(
        "download_requests",
        sa.Column("telegram_delivery_message_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "download_requests",
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_download_requests_delivery_attempt_non_negative",
        "download_requests",
        "delivery_attempt_count >= 0",
    )

    op.create_table(
        "dubbing_workflows",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("source_job_id", sa.UUID(), nullable=False),
        sa.Column("target_language", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="source_ready", nullable=False),
        sa.Column("active_gpu_job_id", sa.UUID(), nullable=True),
        sa.Column("cosyvoice_model", sa.String(length=255), nullable=False),
        sa.Column("sam_model", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )
    op.create_index(op.f("ix_dubbing_workflows_job_id"), "dubbing_workflows", ["job_id"], unique=True)
    op.create_index(op.f("ix_dubbing_workflows_source_job_id"), "dubbing_workflows", ["source_job_id"], unique=False)
    op.create_index(op.f("ix_dubbing_workflows_status"), "dubbing_workflows", ["status"], unique=False)
    op.create_index(op.f("ix_dubbing_workflows_active_gpu_job_id"), "dubbing_workflows", ["active_gpu_job_id"], unique=False)

    op.create_table(
        "dubbing_artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workflow_id", sa.UUID(), nullable=False),
        sa.Column("artifact_type", sa.String(length=64), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("producer", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="ck_dubbing_artifact_size_non_negative"),
        sa.ForeignKeyConstraint(["workflow_id"], ["dubbing_workflows.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workflow_id", "artifact_type", name="uq_dubbing_artifact_type"),
    )
    op.create_index(op.f("ix_dubbing_artifacts_workflow_id"), "dubbing_artifacts", ["workflow_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dubbing_artifacts_workflow_id"), table_name="dubbing_artifacts")
    op.drop_table("dubbing_artifacts")
    op.drop_index(op.f("ix_dubbing_workflows_active_gpu_job_id"), table_name="dubbing_workflows")
    op.drop_index(op.f("ix_dubbing_workflows_status"), table_name="dubbing_workflows")
    op.drop_index(op.f("ix_dubbing_workflows_source_job_id"), table_name="dubbing_workflows")
    op.drop_index(op.f("ix_dubbing_workflows_job_id"), table_name="dubbing_workflows")
    op.drop_table("dubbing_workflows")
    op.drop_constraint(
        "ck_download_requests_delivery_attempt_non_negative",
        "download_requests",
        type_="check",
    )
    op.drop_column("download_requests", "delivered_at")
    op.drop_column("download_requests", "telegram_delivery_message_id")
    op.drop_column("download_requests", "delivery_error")
    op.drop_column("download_requests", "delivery_attempt_count")
    op.drop_column("download_requests", "delivery_status")
