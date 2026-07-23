"""Add chunk_embeddings table with PGVector

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Keep in sync with DEFAULT_EMBEDDING_VECTOR_DIMENSIONS / text-embedding-3-small.
_EMBEDDING_DIMENSIONS = 1536


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "chunk_embeddings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(_EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "dimensions > 0",
            name="ck_chunk_embeddings_dimensions_positive",
        ),
        sa.ForeignKeyConstraint(["chunk_id"], ["content_chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("chunk_id"),
    )
    op.create_index(
        op.f("ix_chunk_embeddings_job_id"),
        "chunk_embeddings",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_chunk_embeddings_job_id_created",
        "chunk_embeddings",
        ["job_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_chunk_embeddings_job_id_created", table_name="chunk_embeddings")
    op.drop_index(op.f("ix_chunk_embeddings_job_id"), table_name="chunk_embeddings")
    op.drop_table("chunk_embeddings")
