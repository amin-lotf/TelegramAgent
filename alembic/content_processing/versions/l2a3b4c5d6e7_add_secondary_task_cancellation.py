"""Add durable secondary-task cancellation scopes.

Revision ID: l2a3b4c5d6e7
Revises: k1f2a3b4c5d6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "k1f2a3b4c5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "secondary_task_cancellations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("cutoff_message_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "matched_active_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "matched_active_count >= 0",
            name="ck_secondary_task_cancellations_matched_count_non_negative",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_secondary_task_cancellations_telegram_user_id"),
        "secondary_task_cancellations",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secondary_task_cancellations_chat_id"),
        "secondary_task_cancellations",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_secondary_task_cancellations_idempotency_key"),
        "secondary_task_cancellations",
        ["idempotency_key"],
        unique=True,
    )
    op.create_index(
        "ix_secondary_task_cancellations_scope_cutoff",
        "secondary_task_cancellations",
        ["telegram_user_id", "chat_id", "cutoff_message_id"],
        unique=False,
    )
    op.add_column(
        "download_requests",
        sa.Column("cancelled_by_id", sa.UUID(), nullable=True),
    )
    op.add_column(
        "download_requests",
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "download_requests",
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_download_requests_cancelled_by_id",
        "download_requests",
        "secondary_task_cancellations",
        ["cancelled_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_download_requests_cancelled_by_id"),
        "download_requests",
        ["cancelled_by_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_download_requests_cancelled_by_id"),
        table_name="download_requests",
    )
    op.drop_constraint(
        "fk_download_requests_cancelled_by_id",
        "download_requests",
        type_="foreignkey",
    )
    op.drop_column("download_requests", "cancelled_at")
    op.drop_column("download_requests", "cancellation_requested_at")
    op.drop_column("download_requests", "cancelled_by_id")
    op.drop_index(
        "ix_secondary_task_cancellations_scope_cutoff",
        table_name="secondary_task_cancellations",
    )
    op.drop_index(
        op.f("ix_secondary_task_cancellations_idempotency_key"),
        table_name="secondary_task_cancellations",
    )
    op.drop_index(
        op.f("ix_secondary_task_cancellations_chat_id"),
        table_name="secondary_task_cancellations",
    )
    op.drop_index(
        op.f("ix_secondary_task_cancellations_telegram_user_id"),
        table_name="secondary_task_cancellations",
    )
    op.drop_table("secondary_task_cancellations")
