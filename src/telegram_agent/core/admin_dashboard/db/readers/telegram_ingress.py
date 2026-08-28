"""SELECT-only queries against the telegram-ingress database."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from telegram_agent.core.admin_dashboard.db.mappings import telegram_ingress as tables
from telegram_agent.core.admin_dashboard.services.view_models import (
    AttachmentRow,
    OutboxRow,
    UserMessageRow,
)


def _attachment_from_row(row: object) -> AttachmentRow:
    return AttachmentRow(
        id=row.id,  # type: ignore[attr-defined]
        user_message_id=row.user_message_id,  # type: ignore[attr-defined]
        file_id=row.file_id,  # type: ignore[attr-defined]
        file_unique_id=row.file_unique_id,  # type: ignore[attr-defined]
        type=row.type,  # type: ignore[attr-defined]
        status=row.status,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
    )


def _message_from_mapping(mapping: dict[str, object], attachment: AttachmentRow | None) -> UserMessageRow:
    return UserMessageRow(
        id=mapping["id"],  # type: ignore[arg-type]
        telegram_user_id=mapping["telegram_user_id"],  # type: ignore[arg-type]
        chat_id=mapping["chat_id"],  # type: ignore[arg-type]
        message_id=mapping["message_id"],  # type: ignore[arg-type]
        update_id=mapping["update_id"],  # type: ignore[arg-type]
        reply_message_id=mapping["reply_message_id"],  # type: ignore[arg-type]
        text=mapping["text"],  # type: ignore[arg-type]
        conversation_status=mapping["conversation_status"],  # type: ignore[arg-type]
        dispatch_event_id=mapping["dispatch_event_id"],  # type: ignore[arg-type]
        created_at=mapping["created_at"],  # type: ignore[arg-type]
        attachment=attachment,
    )


def _outbox_from_row(row: object) -> OutboxRow:
    return OutboxRow(
        id=row.id,  # type: ignore[attr-defined]
        event_type=row.event_type,  # type: ignore[attr-defined]
        status=row.status,  # type: ignore[attr-defined]
        attempt_count=row.attempt_count,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        published_at=row.published_at,  # type: ignore[attr-defined]
        available_at=row.available_at,  # type: ignore[attr-defined]
        locked_at=row.locked_at,  # type: ignore[attr-defined]
        locked_by=row.locked_by,  # type: ignore[attr-defined]
        last_error=row.last_error,  # type: ignore[attr-defined]
        idempotency_key=row.idempotency_key,  # type: ignore[attr-defined]
        payload=dict(row.payload or {}),  # type: ignore[attr-defined]
        chat_id=row.chat_id,  # type: ignore[attr-defined]
        first_message_id=row.first_message_id,  # type: ignore[attr-defined]
    )


class IngressReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _list_filters(
        self,
        *,
        ingress_message_id: UUID | None,
        chat_id: int | None,
        message_id: int | None,
        telegram_user_id: int | None,
        conversation_status: str | None,
        attachment_status: str | None,
        has_attachment: bool | None,
        failed_only: bool,
        created_from: datetime | None,
        created_to: datetime | None,
        text_query: str | None,
    ) -> list[ColumnElement[bool]]:
        um = tables.user_messages
        att = tables.attachments
        conditions: list[ColumnElement[bool]] = []
        if ingress_message_id is not None:
            conditions.append(um.c.id == ingress_message_id)
        if chat_id is not None:
            conditions.append(um.c.chat_id == chat_id)
        if message_id is not None:
            conditions.append(um.c.message_id == message_id)
        if telegram_user_id is not None:
            conditions.append(um.c.telegram_user_id == telegram_user_id)
        if conversation_status:
            conditions.append(um.c.conversation_status == conversation_status)
        if created_from is not None:
            conditions.append(um.c.created_at >= created_from)
        if created_to is not None:
            conditions.append(um.c.created_at <= created_to)
        if text_query:
            conditions.append(um.c.text.ilike(f"%{text_query}%"))
        if has_attachment is True:
            conditions.append(att.c.id.is_not(None))
        if has_attachment is False:
            conditions.append(att.c.id.is_(None))
        if attachment_status:
            conditions.append(att.c.status == attachment_status)
        if failed_only:
            conditions.append(
                or_(
                    um.c.conversation_status == "failed",
                    att.c.status == "failed",
                )
            )
        return conditions

    async def count_messages(
        self,
        *,
        ingress_message_id: UUID | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        telegram_user_id: int | None = None,
        conversation_status: str | None = None,
        attachment_status: str | None = None,
        has_attachment: bool | None = None,
        failed_only: bool = False,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        text_query: str | None = None,
    ) -> int:
        um = tables.user_messages
        att = tables.attachments
        stmt: Select[tuple[int]] = (
            select(func.count())
            .select_from(um.outerjoin(att, att.c.user_message_id == um.c.id))
        )
        conditions = self._list_filters(
            ingress_message_id=ingress_message_id,
            chat_id=chat_id,
            message_id=message_id,
            telegram_user_id=telegram_user_id,
            conversation_status=conversation_status,
            attachment_status=attachment_status,
            has_attachment=has_attachment,
            failed_only=failed_only,
            created_from=created_from,
            created_to=created_to,
            text_query=text_query,
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def list_messages(
        self,
        *,
        limit: int,
        offset: int,
        ingress_message_id: UUID | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        telegram_user_id: int | None = None,
        conversation_status: str | None = None,
        attachment_status: str | None = None,
        has_attachment: bool | None = None,
        failed_only: bool = False,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        text_query: str | None = None,
    ) -> list[UserMessageRow]:
        um = tables.user_messages
        att = tables.attachments
        stmt = (
            select(
                um.c.id,
                um.c.telegram_user_id,
                um.c.chat_id,
                um.c.message_id,
                um.c.update_id,
                um.c.reply_message_id,
                um.c.text,
                um.c.conversation_status,
                um.c.dispatch_event_id,
                um.c.created_at,
                att.c.id.label("att_id"),
                att.c.user_message_id.label("att_user_message_id"),
                att.c.file_id.label("att_file_id"),
                att.c.file_unique_id.label("att_file_unique_id"),
                att.c.type.label("att_type"),
                att.c.status.label("att_status"),
                att.c.created_at.label("att_created_at"),
            )
            .select_from(um.outerjoin(att, att.c.user_message_id == um.c.id))
            .order_by(um.c.created_at.desc(), um.c.id.desc())
            .limit(limit)
            .offset(offset)
        )
        conditions = self._list_filters(
            ingress_message_id=ingress_message_id,
            chat_id=chat_id,
            message_id=message_id,
            telegram_user_id=telegram_user_id,
            conversation_status=conversation_status,
            attachment_status=attachment_status,
            has_attachment=has_attachment,
            failed_only=failed_only,
            created_from=created_from,
            created_to=created_to,
            text_query=text_query,
        )
        if conditions:
            stmt = stmt.where(and_(*conditions))

        result = await self._session.execute(stmt)
        rows: list[UserMessageRow] = []
        for mapping in result.mappings():
            attachment = None
            if mapping["att_id"] is not None:
                attachment = AttachmentRow(
                    id=mapping["att_id"],
                    user_message_id=mapping["att_user_message_id"],
                    file_id=mapping["att_file_id"],
                    file_unique_id=mapping["att_file_unique_id"],
                    type=mapping["att_type"],
                    status=mapping["att_status"],
                    created_at=mapping["att_created_at"],
                )
            rows.append(
                _message_from_mapping(
                    {
                        "id": mapping["id"],
                        "telegram_user_id": mapping["telegram_user_id"],
                        "chat_id": mapping["chat_id"],
                        "message_id": mapping["message_id"],
                        "update_id": mapping["update_id"],
                        "reply_message_id": mapping["reply_message_id"],
                        "text": mapping["text"],
                        "conversation_status": mapping["conversation_status"],
                        "dispatch_event_id": mapping["dispatch_event_id"],
                        "created_at": mapping["created_at"],
                    },
                    attachment,
                )
            )
        return rows

    async def get_message(self, message_id: UUID) -> UserMessageRow | None:
        um = tables.user_messages
        att = tables.attachments
        stmt = (
            select(
                um.c.id,
                um.c.telegram_user_id,
                um.c.chat_id,
                um.c.message_id,
                um.c.update_id,
                um.c.reply_message_id,
                um.c.text,
                um.c.conversation_status,
                um.c.dispatch_event_id,
                um.c.created_at,
                att.c.id.label("att_id"),
                att.c.user_message_id.label("att_user_message_id"),
                att.c.file_id.label("att_file_id"),
                att.c.file_unique_id.label("att_file_unique_id"),
                att.c.type.label("att_type"),
                att.c.status.label("att_status"),
                att.c.created_at.label("att_created_at"),
            )
            .select_from(um.outerjoin(att, att.c.user_message_id == um.c.id))
            .where(um.c.id == message_id)
        )
        result = await self._session.execute(stmt)
        mapping = result.mappings().first()
        if mapping is None:
            return None
        attachment = None
        if mapping["att_id"] is not None:
            attachment = AttachmentRow(
                id=mapping["att_id"],
                user_message_id=mapping["att_user_message_id"],
                file_id=mapping["att_file_id"],
                file_unique_id=mapping["att_file_unique_id"],
                type=mapping["att_type"],
                status=mapping["att_status"],
                created_at=mapping["att_created_at"],
            )
        return _message_from_mapping(
            {
                "id": mapping["id"],
                "telegram_user_id": mapping["telegram_user_id"],
                "chat_id": mapping["chat_id"],
                "message_id": mapping["message_id"],
                "update_id": mapping["update_id"],
                "reply_message_id": mapping["reply_message_id"],
                "text": mapping["text"],
                "conversation_status": mapping["conversation_status"],
                "dispatch_event_id": mapping["dispatch_event_id"],
                "created_at": mapping["created_at"],
            },
            attachment,
        )

    async def get_outbox(self, event_id: UUID) -> OutboxRow | None:
        tbl = tables.conversation_outbox_events
        result = await self._session.execute(select(tbl).where(tbl.c.id == event_id))
        row = result.one_or_none()
        if row is None:
            return None
        return _outbox_from_row(row)
