"""Add reply_to_message_id to download_requests.

Revision ID: j0e1f2a3b4c5
Revises: i9d0e1f2a3b4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0e1f2a3b4c5"
down_revision: Union[str, Sequence[str], None] = "i9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "download_requests",
        sa.Column("reply_to_message_id", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("download_requests", "reply_to_message_id")
