from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.agent_runtime.common.types import (
    AgentMessageRole,
    ClaimStatus,
    CoordinationStatus,
    MessageIntent,
    OutboxEventStatus,
    RuntimeMessageStatus,
)
from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import get_enum_values


class RuntimeBatch(Base):
    __tablename__ = "runtime_batches"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    messages: Mapped[list["RuntimeMessage"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_runtime_batches_idempotency_key",
        ),
    )


class ConversationGroup(Base):
    __tablename__ = "conversation_groups"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    group_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    messages: Mapped[list["RuntimeMessage"]] = relationship(
        back_populates="group",
        foreign_keys="RuntimeMessage.group_id",
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "group_number",
            name="uq_conversation_groups_chat_id_group_number",
        ),
        # Supports composite FK from runtime_messages (group_id, chat_id).
        UniqueConstraint(
            "id",
            "chat_id",
            name="uq_conversation_groups_id_chat_id",
        ),
        CheckConstraint(
            "group_number >= 1",
            name="ck_conversation_groups_group_number_positive",
        ),
    )


class RuntimeMessage(Base):
    __tablename__ = "runtime_messages"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    batch_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    ingress_message_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reply_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    attachment_ingress_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
    )
    attachment_type: Mapped[TelegramAttachmentType | None] = mapped_column(
        sa.Enum(
            TelegramAttachmentType,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=True,
    )
    # Mutable processing state — not part of permanent message identity.
    attachment_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    attachment_file_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attachment_file_unique_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    group_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    coordination_status: Mapped[CoordinationStatus] = mapped_column(
        sa.Enum(
            CoordinationStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=CoordinationStatus.PENDING,
        server_default=CoordinationStatus.PENDING.value,
    )
    status: Mapped[RuntimeMessageStatus] = mapped_column(
        sa.Enum(
            RuntimeMessageStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=RuntimeMessageStatus.RECEIVED,
        server_default=RuntimeMessageStatus.RECEIVED.value,
    )
    intent: Mapped[MessageIntent | None] = mapped_column(
        sa.Enum(
            MessageIntent,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=True,
    )
    coordinated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    batch: Mapped[RuntimeBatch] = relationship(back_populates="messages")
    group: Mapped[ConversationGroup | None] = relationship(
        back_populates="messages",
        foreign_keys=[group_id],
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["batch_id"],
            ["runtime_batches.id"],
            ondelete="CASCADE",
            name="fk_runtime_messages_batch_id",
        ),
        # Prevents a message from referencing a group owned by another chat.
        ForeignKeyConstraint(
            ["group_id", "chat_id"],
            ["conversation_groups.id", "conversation_groups.chat_id"],
            ondelete="RESTRICT",
            name="fk_runtime_messages_group_id_chat_id",
        ),
        UniqueConstraint(
            "ingress_message_id",
            name="uq_runtime_messages_ingress_message_id",
        ),
        UniqueConstraint(
            "chat_id",
            "message_id",
            name="uq_runtime_messages_chat_id_message_id",
        ),
        Index(
            "ix_runtime_messages_chat_pending_order",
            "chat_id",
            "message_id",
            postgresql_where=sa.text("coordination_status = 'pending'"),
        ),
        Index(
            "ix_runtime_messages_chat_message_order",
            "chat_id",
            "message_id",
        ),
        Index(
            "ix_runtime_messages_chat_group_message_order",
            "chat_id",
            "group_id",
            "message_id",
            postgresql_where=sa.text("group_id IS NOT NULL"),
        ),
    )


class ConversationClaim(Base):
    __tablename__ = "conversation_claims"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[ClaimStatus] = mapped_column(
        sa.Enum(
            ClaimStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=ClaimStatus.IDLE,
        server_default=ClaimStatus.IDLE.value,
    )
    claim_token: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "(status <> 'claimed') OR (claim_token IS NOT NULL AND locked_at IS NOT NULL)",
            name="ck_conversation_claims_claimed_requires_token",
        ),
        CheckConstraint(
            "(status <> 'idle') OR ("
            "claim_token IS NULL AND locked_at IS NULL AND locked_by IS NULL"
            ")",
            name="ck_conversation_claims_idle_clears_token",
        ),
        Index(
            "ix_conversation_claims_available",
            "available_at",
            "chat_id",
        ),
        Index(
            "ix_conversation_claims_claimed_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'claimed'"),
        ),
        Index(
            "ix_conversation_claims_claim_token",
            "claim_token",
            unique=True,
            postgresql_where=sa.text("claim_token IS NOT NULL"),
        ),
    )


class OutboxEvent(Base):
    __tablename__ = "coordination_outbox_events"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    runtime_message_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[OutboxEventStatus] = mapped_column(
        sa.Enum(
            OutboxEventStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=OutboxEventStatus.PENDING,
        server_default=OutboxEventStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=sa.text("0"),
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        ForeignKeyConstraint(
            ["runtime_message_id"],
            ["runtime_messages.id"],
            ondelete="CASCADE",
            name="fk_coordination_outbox_events_runtime_message_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_coordination_outbox_events_idempotency_key",
        ),
        UniqueConstraint(
            "runtime_message_id",
            "event_type",
            name="uq_coordination_outbox_events_runtime_message_id_event_type",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_coordination_outbox_events_attempt_count_non_negative",
        ),
        Index(
            "ix_coordination_outbox_events_pending_available",
            "available_at",
            "created_at",
            postgresql_where=sa.text("status = 'pending'"),
        ),
        Index(
            "ix_coordination_outbox_events_chat_pending_order",
            "chat_id",
            "message_id",
            postgresql_where=sa.text("status = 'pending'"),
        ),
        Index(
            "ix_coordination_outbox_events_processing_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'processing'"),
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    ingress_message_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    group_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[AgentMessageRole] = mapped_column(
        sa.Enum(
            AgentMessageRole,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["group_id", "chat_id"],
            ["conversation_groups.id", "conversation_groups.chat_id"],
            ondelete="RESTRICT",
            name="fk_agent_messages_group_id_chat_id",
        ),
        # One reply per agent role and user request. A conversation group can
        # contain multiple independent requests against the same media.
        UniqueConstraint(
            "ingress_message_id",
            "role",
            name="uq_agent_messages_ingress_message_id_role",
        ),
        Index(
            "ix_agent_messages_chat_id_created_at",
            "chat_id",
            "created_at",
        ),
    )
