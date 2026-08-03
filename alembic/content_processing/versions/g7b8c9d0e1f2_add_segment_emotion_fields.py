"""Add emotion and audio_events to transcript_segments

Revision ID: g7b8c9d0e1f2
Revises: f6a7b8c9d0e1

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "g7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transcript_segments",
        sa.Column("emotion", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "transcript_segments",
        sa.Column(
            "audio_events",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("transcript_segments", "audio_events")
    op.drop_column("transcript_segments", "emotion")
