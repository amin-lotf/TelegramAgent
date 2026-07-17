"""First migration

Revision ID: 6d744b6ce486
Revises:


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "6d744b6ce486"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="queued", nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("callback_required", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_jobs_idempotency_key"), "jobs", ["idempotency_key"], unique=True)

    op.create_table(
        "job_completion_expectations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.String(length=64),
            server_default="job_completion",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="open",
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_job_completion_expectations_job_id"),
    )
    op.create_index(
        op.f("ix_job_completion_expectations_job_id"),
        "job_completion_expectations",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        "ix_job_completion_expectations_open_due",
        "job_completion_expectations",
        ["due_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index(
        "ix_job_completion_expectations_processing_lease",
        "job_completion_expectations",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )
    op.create_index(
        "ix_job_completion_expectations_resolved",
        "job_completion_expectations",
        ["resolved_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('satisfied', 'timed_out')"),
    )

    op.create_table(
        "media_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="source", nullable=False),
        sa.Column("parent_asset_id", sa.UUID(), nullable=True),
        sa.Column("local_path", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("mime_type", sa.String(length=128), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["parent_asset_id"],
            ["media_assets.id"],
            ondelete="SET NULL",
            name="fk_media_assets_parent_asset_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "role", name="uq_media_assets_job_id_role"),
    )
    op.create_index(op.f("ix_media_assets_job_id"), "media_assets", ["job_id"], unique=False)
    op.create_index(
        op.f("ix_media_assets_parent_asset_id"),
        "media_assets",
        ["parent_asset_id"],
        unique=False,
    )

    op.create_table(
        "telegram_sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("ingress_message_id", sa.UUID(), nullable=False),
        sa.Column("ingress_attachment_id", sa.UUID(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=512), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(length=255), nullable=True),
        sa.Column("attachment_type", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_telegram_sources_ingress_attachment_id"), "telegram_sources", ["ingress_attachment_id"], unique=False)
    op.create_index(op.f("ix_telegram_sources_ingress_message_id"), "telegram_sources", ["ingress_message_id"], unique=False)
    op.create_index(op.f("ix_telegram_sources_job_id"), "telegram_sources", ["job_id"], unique=True)
    op.create_index(op.f("ix_telegram_sources_telegram_file_unique_id"), "telegram_sources", ["telegram_file_unique_id"], unique=False)
    op.create_index(op.f("ix_telegram_sources_telegram_user_id"), "telegram_sources", ["telegram_user_id"], unique=False)

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="ck_outbox_events_attempt_count_non_negative"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_outbox_events_idempotency_key"),
    )
    op.create_index(op.f("ix_outbox_events_job_id"), "outbox_events", ["job_id"], unique=False)
    op.create_index(
        "ix_outbox_events_pending_available",
        "outbox_events",
        ["available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_outbox_events_processing_lease",
        "outbox_events",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.create_table(
        "transcripts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("language_probability", sa.Float(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_transcripts_job_id"),
    )
    op.create_index(op.f("ix_transcripts_job_id"), "transcripts", ["job_id"], unique=False)

    op.create_table(
        "transcript_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("transcript_id", sa.UUID(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("language_probability", sa.Float(), nullable=True),
        sa.Column("speaker", sa.String(length=64), nullable=True),
        sa.Column("speaker_confidence", sa.Float(), nullable=True),
        sa.CheckConstraint("end_ms >= start_ms", name="ck_transcript_segment_end_after_start"),
        sa.CheckConstraint("segment_index >= 0", name="ck_transcript_segment_index_non_negative"),
        sa.CheckConstraint("start_ms >= 0", name="ck_transcript_segment_start_ms_non_negative"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transcript_id", "segment_index", name="uq_transcript_segment_index"),
    )
    op.create_index(op.f("ix_transcript_segments_transcript_id"), "transcript_segments", ["transcript_id"], unique=False)
    op.create_index("ix_transcript_segments_time", "transcript_segments", ["transcript_id", "start_ms", "end_ms"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index("ix_transcript_segments_time", table_name="transcript_segments")
    op.drop_index(op.f("ix_transcript_segments_transcript_id"), table_name="transcript_segments")
    op.drop_table("transcript_segments")

    op.drop_index(op.f("ix_transcripts_job_id"), table_name="transcripts")
    op.drop_table("transcripts")

    op.drop_index(op.f("ix_telegram_sources_telegram_user_id"), table_name="telegram_sources")
    op.drop_index(op.f("ix_telegram_sources_telegram_file_unique_id"), table_name="telegram_sources")
    op.drop_index(op.f("ix_telegram_sources_job_id"), table_name="telegram_sources")
    op.drop_index(op.f("ix_telegram_sources_ingress_message_id"), table_name="telegram_sources")
    op.drop_index(op.f("ix_telegram_sources_ingress_attachment_id"), table_name="telegram_sources")
    op.drop_table("telegram_sources")

    op.drop_index("ix_outbox_events_processing_lease", table_name="outbox_events")
    op.drop_index("ix_outbox_events_pending_available", table_name="outbox_events")
    op.drop_index(op.f("ix_outbox_events_job_id"), table_name="outbox_events")
    op.drop_table("outbox_events")

    op.drop_index(op.f("ix_media_assets_parent_asset_id"), table_name="media_assets")
    op.drop_index(op.f("ix_media_assets_job_id"), table_name="media_assets")
    op.drop_table("media_assets")

    op.drop_index(
        "ix_job_completion_expectations_resolved",
        table_name="job_completion_expectations",
    )
    op.drop_index(
        "ix_job_completion_expectations_processing_lease",
        table_name="job_completion_expectations",
    )
    op.drop_index(
        "ix_job_completion_expectations_open_due",
        table_name="job_completion_expectations",
    )
    op.drop_index(
        op.f("ix_job_completion_expectations_job_id"),
        table_name="job_completion_expectations",
    )
    op.drop_table("job_completion_expectations")

    op.drop_index(op.f("ix_jobs_idempotency_key"), table_name="jobs")
    op.drop_table("jobs")
