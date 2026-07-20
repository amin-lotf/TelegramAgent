"""Add subtitle translation tables

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subtitle_translations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("source_language", sa.String(length=32), nullable=True),
        sa.Column("target_language", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("glossary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "target_language",
            name="uq_subtitle_translations_job_language",
        ),
    )
    op.create_index(
        op.f("ix_subtitle_translations_job_id"),
        "subtitle_translations",
        ["job_id"],
        unique=False,
    )

    op.create_table(
        "translation_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subtitle_translation_id", sa.UUID(), nullable=False),
        sa.Column("batch_index", sa.Integer(), nullable=False),
        sa.Column("start_segment_index", sa.Integer(), nullable=False),
        sa.Column("end_segment_index", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("provider_request_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "batch_index >= 0",
            name="ck_translation_batches_batch_index_non_negative",
        ),
        sa.CheckConstraint(
            "start_segment_index >= 0",
            name="ck_translation_batches_start_segment_non_negative",
        ),
        sa.CheckConstraint(
            "end_segment_index >= start_segment_index",
            name="ck_translation_batches_end_after_start",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_translation_batches_attempt_count_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["subtitle_translation_id"],
            ["subtitle_translations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subtitle_translation_id",
            "batch_index",
            name="uq_translation_batches_translation_index",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_translation_batches_idempotency_key",
        ),
    )
    op.create_index(
        op.f("ix_translation_batches_subtitle_translation_id"),
        "translation_batches",
        ["subtitle_translation_id"],
        unique=False,
    )
    op.create_index(
        "ix_translation_batches_claimable",
        "translation_batches",
        ["subtitle_translation_id", "status", "batch_index"],
        unique=False,
    )
    op.create_index(
        "ix_translation_batches_processing_lease",
        "translation_batches",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )

    op.create_table(
        "translated_segments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("subtitle_translation_id", sa.UUID(), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "segment_index >= 0",
            name="ck_translated_segments_index_non_negative",
        ),
        sa.CheckConstraint(
            "start_ms >= 0",
            name="ck_translated_segments_start_ms_non_negative",
        ),
        sa.CheckConstraint(
            "end_ms >= start_ms",
            name="ck_translated_segments_end_after_start",
        ),
        sa.ForeignKeyConstraint(
            ["subtitle_translation_id"],
            ["subtitle_translations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subtitle_translation_id",
            "segment_index",
            name="uq_translated_segments_translation_index",
        ),
    )
    op.create_index(
        op.f("ix_translated_segments_subtitle_translation_id"),
        "translated_segments",
        ["subtitle_translation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_translated_segments_subtitle_translation_id"),
        table_name="translated_segments",
    )
    op.drop_table("translated_segments")
    op.drop_index(
        "ix_translation_batches_processing_lease",
        table_name="translation_batches",
    )
    op.drop_index("ix_translation_batches_claimable", table_name="translation_batches")
    op.drop_index(
        op.f("ix_translation_batches_subtitle_translation_id"),
        table_name="translation_batches",
    )
    op.drop_table("translation_batches")
    op.drop_index(
        op.f("ix_subtitle_translations_job_id"),
        table_name="subtitle_translations",
    )
    op.drop_table("subtitle_translations")
