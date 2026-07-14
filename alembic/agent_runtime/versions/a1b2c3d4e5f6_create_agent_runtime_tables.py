"""create agent runtime tables

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-07-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_batches",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_runtime_batches_idempotency_key"),
    )
    op.create_index(
        op.f("ix_runtime_batches_chat_id"),
        "runtime_batches",
        ["chat_id"],
        unique=False,
    )

    op.create_table(
        "conversation_groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("group_number", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "group_number >= 1",
            name="ck_conversation_groups_group_number_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_id",
            "group_number",
            name="uq_conversation_groups_chat_id_group_number",
        ),
        sa.UniqueConstraint(
            "id",
            "chat_id",
            name="uq_conversation_groups_id_chat_id",
        ),
    )
    op.create_index(
        op.f("ix_conversation_groups_chat_id"),
        "conversation_groups",
        ["chat_id"],
        unique=False,
    )

    op.create_table(
        "conversation_claims",
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("idle", "claimed", name="claimstatus", native_enum=False, length=32),
            server_default="idle",
            nullable=False,
        ),
        sa.Column("claim_token", sa.UUID(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column(
            "available_at",
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
            "(status <> 'claimed') OR (claim_token IS NOT NULL AND locked_at IS NOT NULL)",
            name="ck_conversation_claims_claimed_requires_token",
        ),
        sa.CheckConstraint(
            "(status <> 'idle') OR ("
            "claim_token IS NULL AND locked_at IS NULL AND locked_by IS NULL"
            ")",
            name="ck_conversation_claims_idle_clears_token",
        ),
        sa.PrimaryKeyConstraint("chat_id"),
    )
    op.create_index(
        "ix_conversation_claims_available",
        "conversation_claims",
        ["available_at", "chat_id"],
        unique=False,
    )
    op.create_index(
        "ix_conversation_claims_claimed_lease",
        "conversation_claims",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'claimed'"),
    )
    op.create_index(
        "ix_conversation_claims_claim_token",
        "conversation_claims",
        ["claim_token"],
        unique=True,
        postgresql_where=sa.text("claim_token IS NOT NULL"),
    )

    op.create_table(
        "runtime_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=False),
        sa.Column("ingress_message_id", sa.UUID(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("reply_message_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("attachment_ingress_id", sa.UUID(), nullable=True),
        sa.Column(
            "attachment_type",
            sa.Enum(
                "voice",
                "video",
                "video_note",
                "document",
                "audio",
                "photo",
                name="telegramattachmenttype",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("attachment_status", sa.String(length=32), nullable=True),
        sa.Column("attachment_file_id", sa.String(length=512), nullable=True),
        sa.Column("attachment_file_unique_id", sa.String(length=255), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column(
            "coordination_status",
            sa.Enum(
                "pending",
                "grouped",
                "vague",
                name="coordinationstatus",
                native_enum=False,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("coordinated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["runtime_batches.id"],
            ondelete="CASCADE",
            name="fk_runtime_messages_batch_id",
        ),
        sa.ForeignKeyConstraint(
            ["group_id", "chat_id"],
            ["conversation_groups.id", "conversation_groups.chat_id"],
            ondelete="SET NULL",
            name="fk_runtime_messages_group_id_chat_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "chat_id",
            "message_id",
            name="uq_runtime_messages_chat_id_message_id",
        ),
        sa.UniqueConstraint(
            "ingress_message_id",
            name="uq_runtime_messages_ingress_message_id",
        ),
    )
    op.create_index(
        op.f("ix_runtime_messages_batch_id"),
        "runtime_messages",
        ["batch_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_messages_chat_id"),
        "runtime_messages",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_messages_group_id"),
        "runtime_messages",
        ["group_id"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_messages_chat_message_order",
        "runtime_messages",
        ["chat_id", "message_id"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_messages_chat_pending_order",
        "runtime_messages",
        ["chat_id", "message_id"],
        unique=False,
        postgresql_where=sa.text("coordination_status = 'pending'"),
    )
    op.create_index(
        "ix_runtime_messages_chat_group_message_order",
        "runtime_messages",
        ["chat_id", "group_id", "message_id"],
        unique=False,
        postgresql_where=sa.text("group_id IS NOT NULL"),
    )

    op.create_table(
        "coordination_outbox_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("runtime_message_id", sa.UUID(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "published",
                "failed",
                name="outboxeventstatus",
                native_enum=False,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_coordination_outbox_events_attempt_count_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["runtime_message_id"],
            ["runtime_messages.id"],
            ondelete="CASCADE",
            name="fk_coordination_outbox_events_runtime_message_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_coordination_outbox_events_idempotency_key",
        ),
        sa.UniqueConstraint(
            "runtime_message_id",
            name="uq_coordination_outbox_events_runtime_message_id",
        ),
    )
    op.create_index(
        op.f("ix_coordination_outbox_events_chat_id"),
        "coordination_outbox_events",
        ["chat_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_coordination_outbox_events_runtime_message_id"),
        "coordination_outbox_events",
        ["runtime_message_id"],
        unique=False,
    )
    op.create_index(
        "ix_coordination_outbox_events_chat_pending_order",
        "coordination_outbox_events",
        ["chat_id", "message_id"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_coordination_outbox_events_pending_available",
        "coordination_outbox_events",
        ["available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_coordination_outbox_events_processing_lease",
        "coordination_outbox_events",
        ["locked_at"],
        unique=False,
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_coordination_outbox_events_processing_lease",
        table_name="coordination_outbox_events",
    )
    op.drop_index(
        "ix_coordination_outbox_events_pending_available",
        table_name="coordination_outbox_events",
    )
    op.drop_index(
        "ix_coordination_outbox_events_chat_pending_order",
        table_name="coordination_outbox_events",
    )
    op.drop_index(
        op.f("ix_coordination_outbox_events_runtime_message_id"),
        table_name="coordination_outbox_events",
    )
    op.drop_index(
        op.f("ix_coordination_outbox_events_chat_id"),
        table_name="coordination_outbox_events",
    )
    op.drop_table("coordination_outbox_events")

    op.drop_index(
        "ix_runtime_messages_chat_group_message_order",
        table_name="runtime_messages",
    )
    op.drop_index("ix_runtime_messages_chat_pending_order", table_name="runtime_messages")
    op.drop_index("ix_runtime_messages_chat_message_order", table_name="runtime_messages")
    op.drop_index(op.f("ix_runtime_messages_group_id"), table_name="runtime_messages")
    op.drop_index(op.f("ix_runtime_messages_chat_id"), table_name="runtime_messages")
    op.drop_index(op.f("ix_runtime_messages_batch_id"), table_name="runtime_messages")
    op.drop_table("runtime_messages")

    op.drop_index("ix_conversation_claims_claim_token", table_name="conversation_claims")
    op.drop_index("ix_conversation_claims_claimed_lease", table_name="conversation_claims")
    op.drop_index("ix_conversation_claims_available", table_name="conversation_claims")
    op.drop_table("conversation_claims")

    op.drop_index(op.f("ix_conversation_groups_chat_id"), table_name="conversation_groups")
    op.drop_table("conversation_groups")

    op.drop_index(op.f("ix_runtime_batches_chat_id"), table_name="runtime_batches")
    op.drop_table("runtime_batches")
