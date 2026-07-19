"""Add download_requests table

Revision ID: c3d4e5f6a7b8
Revises: 6d744b6ce486

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "6d744b6ce486"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "download_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("job_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("agent_message_id", sa.UUID(), nullable=False),
        sa.Column("media_ingress_message_id", sa.UUID(), nullable=False),
        sa.Column("media_type", sa.String(length=32), nullable=False),
        sa.Column("requested_subtitle_language", sa.String(length=64), nullable=True),
        sa.Column("requested_dub_language", sa.String(length=64), nullable=True),
        sa.Column("requested_language", sa.String(length=64), nullable=True),
        sa.Column("requested_format", sa.String(length=64), nullable=True),
        sa.Column("assistant_text", sa.Text(), nullable=True),
        sa.Column("final_path", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_download_requests_job_id"),
    )
    op.create_index(
        op.f("ix_download_requests_job_id"),
        "download_requests",
        ["job_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_download_requests_chat_id"),
        "download_requests",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_download_requests_telegram_user_id"),
        "download_requests",
        ["telegram_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_download_requests_group_id"),
        "download_requests",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_download_requests_agent_message_id"),
        "download_requests",
        ["agent_message_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_download_requests_media_ingress_message_id"),
        "download_requests",
        ["media_ingress_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_download_requests_media_ingress_message_id"),
        table_name="download_requests",
    )
    op.drop_index(
        op.f("ix_download_requests_agent_message_id"),
        table_name="download_requests",
    )
    op.drop_index(op.f("ix_download_requests_group_id"), table_name="download_requests")
    op.drop_index(
        op.f("ix_download_requests_telegram_user_id"),
        table_name="download_requests",
    )
    op.drop_index(op.f("ix_download_requests_chat_id"), table_name="download_requests")
    op.drop_index(op.f("ix_download_requests_job_id"), table_name="download_requests")
    op.drop_table("download_requests")
