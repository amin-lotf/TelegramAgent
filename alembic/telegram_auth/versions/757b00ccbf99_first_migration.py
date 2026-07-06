"""First migration

Revision ID: 757b00ccbf99
Revises:


"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "757b00ccbf99"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "telegram_users",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),

        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),

        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),

        sa.Column(
            "is_bot",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),

        sa.Column("language_code", sa.String(length=20), nullable=True),

        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),

        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),

        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_telegram_users_telegram_user_id",
        "telegram_users",
        ["telegram_user_id"],
        unique=True,
    )

    op.create_index(
        "ix_telegram_users_chat_id",
        "telegram_users",
        ["chat_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    op.drop_index(
        "ix_telegram_users_chat_id",
        table_name="telegram_users",
    )

    op.drop_index(
        "ix_telegram_users_telegram_user_id",
        table_name="telegram_users",
    )

    op.drop_table("telegram_users")