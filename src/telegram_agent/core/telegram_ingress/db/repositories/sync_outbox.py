from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, aliased

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.telegram_ingress.common.types import OutboxEventStatus
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent


class SyncSqlAlchemyConversationOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, event_id: UUID) -> ConversationOutboxEvent | None:
        stmt = (
            select(ConversationOutboxEvent)
            .where(ConversationOutboxEvent.id == event_id)
        )
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def claim_available(
            self,
            *,
            batch_size: int,
            lease_owner: str,
            lease_timeout: timedelta,
    ) -> list[ConversationOutboxEvent]:
        now = utcnow()
        expired_before = now - lease_timeout
        older_event = aliased(ConversationOutboxEvent)
        older_unfinished_event_exists = exists(
            select(older_event.id).where(
                older_event.chat_id == ConversationOutboxEvent.chat_id,
                older_event.first_message_id < ConversationOutboxEvent.first_message_id,
                older_event.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                ),
            )
        )
        locked_ids_statement = (
            select(ConversationOutboxEvent.id)
            .where(
                or_(
                    and_(
                        ConversationOutboxEvent.status == OutboxEventStatus.PENDING,
                        ConversationOutboxEvent.available_at <= now,
                    ),
                    and_(
                        ConversationOutboxEvent.status == OutboxEventStatus.PROCESSING,
                        ConversationOutboxEvent.locked_at < expired_before,
                    ),
                ),
                ~older_unfinished_event_exists,
            )
            .order_by(ConversationOutboxEvent.created_at, ConversationOutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        locked_ids = list(self._session.scalars(locked_ids_statement).all())
        if not locked_ids:
            return []

        update_statement = (
            update(ConversationOutboxEvent)
            .where(ConversationOutboxEvent.id.in_(locked_ids))
            .values(
                status=OutboxEventStatus.PROCESSING,
                locked_at=now,
                locked_by=lease_owner,
            )
            .returning(ConversationOutboxEvent)
        )
        result = self._session.execute(update_statement)
        claimed_by_id = {event.id: event for event in result.scalars().all()}
        return [claimed_by_id[event_id] for event_id in locked_ids if event_id in claimed_by_id]

    def mark_published(
            self,
            *,
            event_id: UUID,
            lease_owner: str,
    ) -> ConversationOutboxEvent | None:
        statement = (
            update(ConversationOutboxEvent)
            .where(
                ConversationOutboxEvent.id == event_id,
                ConversationOutboxEvent.status == OutboxEventStatus.PROCESSING,
                ConversationOutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.PUBLISHED,
                published_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(ConversationOutboxEvent)
        )
        result = self._session.execute(statement)
        return result.scalar_one_or_none()

    def record_failure(
            self,
            *,
            event_id: UUID,
            lease_owner: str,
            error_message: str,
            next_available_at: datetime,
    ) -> ConversationOutboxEvent | None:
        statement = (
            update(ConversationOutboxEvent)
            .where(
                ConversationOutboxEvent.id == event_id,
                ConversationOutboxEvent.status == OutboxEventStatus.PROCESSING,
                ConversationOutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.PENDING,
                attempt_count=ConversationOutboxEvent.attempt_count + 1,
                available_at=next_available_at,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
            )
            .returning(ConversationOutboxEvent)
        )
        result = self._session.execute(statement)
        return result.scalar_one_or_none()

    def mark_failed(
            self,
            *,
            event_id: UUID,
            lease_owner: str,
            error_message: str,
    ) -> ConversationOutboxEvent | None:
        statement = (
            update(ConversationOutboxEvent)
            .where(
                ConversationOutboxEvent.id == event_id,
                ConversationOutboxEvent.status == OutboxEventStatus.PROCESSING,
                ConversationOutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.FAILED,
                attempt_count=ConversationOutboxEvent.attempt_count + 1,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
            )
            .returning(ConversationOutboxEvent)
        )
        result = self._session.execute(statement)
        return result.scalar_one_or_none()

    def recover_expired_leases(self, *, lease_timeout: timedelta) -> int:
        expired_before = utcnow() - lease_timeout
        statement = (
            update(ConversationOutboxEvent)
            .where(
                ConversationOutboxEvent.status == OutboxEventStatus.PROCESSING,
                ConversationOutboxEvent.locked_at < expired_before,
            )
            .values(
                status=OutboxEventStatus.PENDING,
                locked_at=None,
                locked_by=None,
            )
        )
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)
