"""add agent_messages table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ingress_message_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "download_agent",
                name="agentmessagerole",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "chat_id"],
            ["conversation_groups.id", "conversation_groups.chat_id"],
            ondelete="RESTRICT",
            name="fk_agent_messages_group_id_chat_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id",
            "role",
            name="uq_agent_messages_group_id_role",
        ),
    )
    op.create_index(
        op.f("ix_agent_messages_chat_id"),
        "agent_messages",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_agent_messages_group_id"),
        "agent_messages",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_messages_chat_id_created_at",
        "agent_messages",
        ["chat_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_agent_messages_chat_id_created_at",
        table_name="agent_messages",
    )
    op.drop_index(op.f("ix_agent_messages_group_id"), table_name="agent_messages")
    op.drop_index(op.f("ix_agent_messages_chat_id"), table_name="agent_messages")
    op.drop_table("agent_messages")
