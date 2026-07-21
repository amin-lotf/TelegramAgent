"""Add content_chunks table

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "content_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column(
            "content_type",
            sa.String(length=32),
            server_default="transcript",
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("segment_index_start", sa.Integer(), nullable=True),
        sa.Column("segment_index_end", sa.Integer(), nullable=True),
        sa.Column("speakers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("strategy", sa.String(length=128), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_content_chunks_chunk_index_non_negative",
        ),
        sa.CheckConstraint(
            "char_count >= 0",
            name="ck_content_chunks_char_count_non_negative",
        ),
        sa.CheckConstraint(
            "start_ms IS NULL OR start_ms >= 0",
            name="ck_content_chunks_start_ms_non_negative",
        ),
        sa.CheckConstraint(
            "end_ms IS NULL OR start_ms IS NULL OR end_ms >= start_ms",
            name="ck_content_chunks_end_after_start",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "content_type",
            "chunk_index",
            name="uq_content_chunks_job_type_index",
        ),
    )
    op.create_index(
        op.f("ix_content_chunks_job_id"),
        "content_chunks",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_content_chunks_job_type",
        "content_chunks",
        ["job_id", "content_type"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_chunks_job_type", table_name="content_chunks")
    op.drop_index(op.f("ix_content_chunks_job_id"), table_name="content_chunks")
    op.drop_table("content_chunks")
