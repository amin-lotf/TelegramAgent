from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from telegram_agent.core.common.db.base import Base
from telegram_agent.core.common.utils import get_enum_values
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus
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




class VoiceAttachment(Base):
    __tablename__ = "voice_attachments"

    attachment_id: Mapped[UUID] = mapped_column(
        sa.UUID(as_uuid=True),
        ForeignKey("attachments.id", ondelete="CASCADE"),
        primary_key=True,
    )

    audio_path: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    duration_seconds: Mapped[float | None] = mapped_column(
        sa.Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    attachment: Mapped[Attachment] = relationship()