from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.gpu_execution.common.types import GpuOutboxStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuOutboxEvent


class SyncSqlAlchemyGpuOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: GpuOutboxEvent) -> GpuOutboxEvent:
        self._session.add(event)
        self._session.flush()
        return event

    def get_by_delivery_key(self, delivery_key: str) -> GpuOutboxEvent | None:
        return self._session.scalar(
            select(GpuOutboxEvent).where(GpuOutboxEvent.delivery_key == delivery_key)
        )

    def claim_available(
        self,
        *,
        batch_size: int,
        lease_owner: str,
        lease_timeout: timedelta,
    ) -> list[GpuOutboxEvent]:
        now = utcnow()
        expired_before = now - lease_timeout
        ids = list(
            self._session.scalars(
                select(GpuOutboxEvent.id)
                .where(
                    or_(
                        and_(
                            GpuOutboxEvent.status == GpuOutboxStatus.PENDING,
                            GpuOutboxEvent.available_at <= now,
                        ),
                        and_(
                            GpuOutboxEvent.status == GpuOutboxStatus.PROCESSING,
                            GpuOutboxEvent.locked_at < expired_before,
                        ),
                    )
                )
                .order_by(GpuOutboxEvent.available_at, GpuOutboxEvent.created_at, GpuOutboxEvent.id)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        if not ids:
            return []
        events = list(
            self._session.scalars(
                update(GpuOutboxEvent)
                .where(GpuOutboxEvent.id.in_(ids))
                .values(
                    status=GpuOutboxStatus.PROCESSING,
                    locked_at=now,
                    locked_by=lease_owner,
                )
                .returning(GpuOutboxEvent)
            )
        )
        by_id = {event.id: event for event in events}
        return [by_id[event_id] for event_id in ids]

    def mark_published(self, *, event_id: UUID, lease_owner: str) -> bool:
        statement = (
            update(GpuOutboxEvent)
            .where(
                GpuOutboxEvent.id == event_id,
                GpuOutboxEvent.status == GpuOutboxStatus.PROCESSING,
                GpuOutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=GpuOutboxStatus.PUBLISHED,
                published_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(GpuOutboxEvent.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def record_failure(
        self,
        *,
        event_id: UUID,
        lease_owner: str,
        error_message: str,
        retry_delay: timedelta,
    ) -> bool:
        statement = (
            update(GpuOutboxEvent)
            .where(
                GpuOutboxEvent.id == event_id,
                GpuOutboxEvent.status == GpuOutboxStatus.PROCESSING,
                GpuOutboxEvent.locked_by == lease_owner,
            )
            .values(
                status=GpuOutboxStatus.PENDING,
                available_at=utcnow() + retry_delay,
                locked_at=None,
                locked_by=None,
                last_error=clean_error_message(error_message, max_length=2000),
            )
            .returning(GpuOutboxEvent.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None
