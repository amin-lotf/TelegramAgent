from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus, ConversationStatus
from telegram_agent.core.common.types import TelegramAttachmentType


class UserMessage(Base):
    __tablename__ = "user_messages"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    telegram_user_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    chat_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
    )

    message_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
    )

    update_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    reply_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
    )

    # This stores either Telegram text or caption.
    # It can be NULL/empty until voice/audio transcription finishes.
    text: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    conversation_status: Mapped[ConversationStatus] = mapped_column(
        sa.Enum(
            ConversationStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=ConversationStatus.PENDING,
        server_default=ConversationStatus.PENDING.value,
    )

    dispatch_event_id: Mapped[UUID | None] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("conversation_outbox_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    attachment: Mapped[Attachment | None] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "message_id",
            name="uq_user_messages_chat_id_message_id",
        ),
        UniqueConstraint(
            "update_id",
            name="uq_user_messages_update_id",
        ),
        Index(
            "ix_user_messages_chat_pending_order",
            "chat_id",
            "message_id",
            postgresql_where=sa.text("conversation_status = 'pending'"),
        ),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    user_message_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("user_messages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    file_id: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )

    file_unique_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )

    type: Mapped[TelegramAttachmentType] = mapped_column(
        sa.Enum(
            TelegramAttachmentType,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
    )

    status: Mapped[AttachmentStatus] = mapped_column(
        sa.Enum(
            AttachmentStatus,
            values_callable=get_enum_values,
            native_enum=False,
            length=32,
        ),
        nullable=False,
        default=AttachmentStatus.PENDING,
        server_default=AttachmentStatus.PENDING.value,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    message: Mapped[UserMessage] = relationship(
        back_populates="attachment",
    )
