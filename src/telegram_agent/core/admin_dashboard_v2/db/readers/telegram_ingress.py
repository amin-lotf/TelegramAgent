from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select, tuple_

from telegram_agent.core.admin_dashboard_v2.common.types import (
    CursorPosition,
    MessageListFilters,
)
from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.db.tables.telegram_ingress import (
    attachments,
    conversation_outbox_events,
    user_messages,
)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


class TelegramIngressReader:
    source = "telegram_ingress"

    def __init__(self, databases: ReadDatabaseManager) -> None:
        self._databases = databases

    async def list_messages(
        self,
        *,
        filters: MessageListFilters,
        cursor: CursorPosition | None,
        limit: int,
        allowed_ingress_ids: Collection[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        if allowed_ingress_ids is not None and not allowed_ingress_ids:
            return []
        columns = [
            user_messages.c.id,
            user_messages.c.telegram_user_id,
            user_messages.c.chat_id,
            user_messages.c.message_id,
            user_messages.c.update_id,
            user_messages.c.reply_message_id,
            user_messages.c.text,
            user_messages.c.conversation_status,
            user_messages.c.dispatch_event_id,
            user_messages.c.created_at,
            attachments.c.id.label("attachment_id"),
            attachments.c.file_id.label("attachment_file_id"),
            attachments.c.file_unique_id.label("attachment_file_unique_id"),
            attachments.c.type.label("attachment_type"),
            attachments.c.status.label("attachment_status"),
            attachments.c.created_at.label("attachment_created_at"),
        ]
        statement = (
            select(*columns)
            .select_from(
                user_messages.outerjoin(
                    attachments,
                    attachments.c.user_message_id == user_messages.c.id,
                )
            )
            .order_by(user_messages.c.created_at.desc(), user_messages.c.id.desc())
            .limit(limit)
        )
        conditions = []
        if filters.ingress_message_id is not None:
            conditions.append(user_messages.c.id == filters.ingress_message_id)
        if filters.chat_id is not None:
            conditions.append(user_messages.c.chat_id == filters.chat_id)
        if filters.message_id is not None:
            conditions.append(user_messages.c.message_id == filters.message_id)
        if filters.update_id is not None:
            conditions.append(user_messages.c.update_id == filters.update_id)
        if filters.telegram_user_id is not None:
            conditions.append(user_messages.c.telegram_user_id == filters.telegram_user_id)
        if filters.date_from is not None:
            conditions.append(user_messages.c.created_at >= filters.date_from)
        if filters.date_to is not None:
            conditions.append(user_messages.c.created_at < filters.date_to)
        if filters.ingress_status is not None:
            conditions.append(user_messages.c.conversation_status == filters.ingress_status)
        if filters.attachment_status is not None:
            conditions.append(attachments.c.status == filters.attachment_status)
        if filters.attachment_type is not None:
            conditions.append(attachments.c.type == filters.attachment_type)
        if filters.has_attachment is True:
            conditions.append(attachments.c.id.is_not(None))
        elif filters.has_attachment is False:
            conditions.append(attachments.c.id.is_(None))
        if cursor is not None:
            conditions.append(
                tuple_(user_messages.c.created_at, user_messages.c.id)
                < tuple_(cursor.created_at, cursor.message_id)
            )
        if allowed_ingress_ids is not None:
            conditions.append(user_messages.c.id.in_(allowed_ingress_ids))
        if conditions:
            statement = statement.where(and_(*conditions))

        async with self._databases.connection(self.source) as connection:
            rows = (await connection.execute(statement)).all()
        return [_mapping(row) for row in rows]

    async def get_trace(self, ingress_message_id: UUID, *, sibling_limit: int) -> dict[str, Any] | None:
        message_statement = (
            select(
                *user_messages.c,
                attachments.c.id.label("attachment_id"),
                attachments.c.file_id.label("attachment_file_id"),
                attachments.c.file_unique_id.label("attachment_file_unique_id"),
                attachments.c.type.label("attachment_type"),
                attachments.c.status.label("attachment_status"),
                attachments.c.created_at.label("attachment_created_at"),
            )
            .select_from(
                user_messages.outerjoin(
                    attachments,
                    attachments.c.user_message_id == user_messages.c.id,
                )
            )
            .where(user_messages.c.id == ingress_message_id)
        )
        async with self._databases.connection(self.source) as connection:
            row = (await connection.execute(message_statement)).one_or_none()
            if row is None:
                return None
            message = _mapping(row)
            outbox = None
            siblings: list[dict[str, Any]] = []
            dispatch_event_id = message["dispatch_event_id"]
            if dispatch_event_id is not None:
                outbox_row = (
                    await connection.execute(
                        select(conversation_outbox_events).where(
                            conversation_outbox_events.c.id == dispatch_event_id
                        )
                    )
                ).one_or_none()
                outbox = _mapping(outbox_row) if outbox_row is not None else None
                sibling_rows = (
                    await connection.execute(
                        select(
                            user_messages.c.id,
                            user_messages.c.message_id,
                            user_messages.c.text,
                            user_messages.c.conversation_status,
                            user_messages.c.created_at,
                        )
                        .where(user_messages.c.dispatch_event_id == dispatch_event_id)
                        .order_by(user_messages.c.message_id, user_messages.c.id)
                        .limit(sibling_limit)
                    )
                ).all()
                siblings = [_mapping(item) for item in sibling_rows]
        attachment = None
        if message["attachment_id"] is not None:
            attachment = {
                "id": message.pop("attachment_id"),
                "file_id": message.pop("attachment_file_id"),
                "file_unique_id": message.pop("attachment_file_unique_id"),
                "type": message.pop("attachment_type"),
                "status": message.pop("attachment_status"),
                "created_at": message.pop("attachment_created_at"),
            }
        else:
            for key in (
                "attachment_id",
                "attachment_file_id",
                "attachment_file_unique_id",
                "attachment_type",
                "attachment_status",
                "attachment_created_at",
            ):
                message.pop(key, None)
        return {
            "message": message,
            "attachment": attachment,
            "outbox": outbox,
            "batch_siblings": siblings,
            "batch_siblings_truncated": len(siblings) >= sibling_limit,
        }
