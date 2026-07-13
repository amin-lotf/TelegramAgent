from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.telegram_ingress.common.types import OutboxEventStatus


class ConversationOutboxEvent(Base):
    __tablename__ = "conversation_outbox_events"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    first_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "first_message_id",
            name="uq_conversation_outbox_events_chat_first_message",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_conversation_outbox_events_idempotency_key",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_conversation_outbox_events_attempt_count_non_negative",
        ),
        Index(
            "ix_conversation_outbox_events_pending_available",
            "available_at",
            "created_at",
            postgresql_where=sa.text("status = 'pending'"),
        ),
        Index(
            "ix_conversation_outbox_events_processing_lease",
            "locked_at",
            postgresql_where=sa.text("status = 'processing'"),
        ),
    )
