from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.content_processing.common.types import OutboxEventStatus
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent


class SyncSqlAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> OutboxEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def get_by_id(self, event_id: UUID) -> OutboxEvent | None:
        stmt = select(OutboxEvent).where(OutboxEvent.id == event_id)
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def claim_available(
        self,
        *,
        batch_size: int,
        lease_owner: str,
        lease_timeout: timedelta,
    ) -> list[OutboxEvent]:
        now = utcnow()
        expired_before = now - lease_timeout

        locked_ids_stmt = (
            select(OutboxEvent.id)
            .where(
                or_(
                    and_(
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                        OutboxEvent.available_at <= now,
                    ),
                    and_(
                        OutboxEvent.status == OutboxEventStatus.PROCESSING,
                        OutboxEvent.locked_at < expired_before,
                    ),
                )
            )
            .order_by(OutboxEvent.created_at, OutboxEvent.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        locked_ids = list(self._session.scalars(locked_ids_stmt).all())
        if not locked_ids:
            return []

        update_stmt = (
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(locked_ids))
            .values(
                status=OutboxEventStatus.PROCESSING,
                locked_at=now,
                locked_by=lease_owner,
            )
            .returning(OutboxEvent)
        )
        result = self._session.execute(update_stmt)
        claimed_by_id = {event.id: event for event in result.scalars().all()}
        return [claimed_by_id[event_id] for event_id in locked_ids if event_id in claimed_by_id]

    def mark_published(
        self,
        *,
        event_id: UUID,
        lease_owner: str,
    ) -> OutboxEvent | None:
        stmt = (
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxEventStatus.PROCESSING,
                OutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.PUBLISHED,
                published_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(OutboxEvent)
        )
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def record_failure(
        self,
        *,
        event_id: UUID,
        lease_owner: str,
        error_message: str,
        next_available_at: datetime,
    ) -> OutboxEvent | None:
        stmt = (
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxEventStatus.PROCESSING,
                OutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.PENDING,
                attempt_count=OutboxEvent.attempt_count + 1,
                available_at=next_available_at,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
            )
            .returning(OutboxEvent)
        )
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def mark_failed(
        self,
        *,
        event_id: UUID,
        lease_owner: str,
        error_message: str,
    ) -> OutboxEvent | None:
        stmt = (
            update(OutboxEvent)
            .where(
                OutboxEvent.id == event_id,
                OutboxEvent.status == OutboxEventStatus.PROCESSING,
                OutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=OutboxEventStatus.FAILED,
                attempt_count=OutboxEvent.attempt_count + 1,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
            )
            .returning(OutboxEvent)
        )
        result = self._session.execute(stmt)
        return result.scalar_one_or_none()

    def recover_expired_leases(
        self,
        *,
        lease_timeout: timedelta,
    ) -> int:
        expired_before = utcnow() - lease_timeout
        stmt = (
            update(OutboxEvent)
            .where(
                OutboxEvent.status == OutboxEventStatus.PROCESSING,
                OutboxEvent.locked_at < expired_before,
            )
            .values(
                status=OutboxEventStatus.PENDING,
                locked_at=None,
                locked_by=None,
            )
        )
        result = self._session.execute(stmt)
        return int(cast(CursorResult, result).rowcount or 0)
