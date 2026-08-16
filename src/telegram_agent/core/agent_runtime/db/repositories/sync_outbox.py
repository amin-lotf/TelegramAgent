from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import Exists

from telegram_agent.core.agent_runtime.common.types import (
    ClaimStatus,
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
)
from telegram_agent.core.common.utils import clean_error_message, utcnow


class SyncSqlAlchemyOutboxRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: OutboxEvent) -> OutboxEvent:
        self._session.add(event)
        return event

    def get_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None:
        statement = select(OutboxEvent).where(
            OutboxEvent.idempotency_key == idempotency_key
        )
        return self._session.scalar(statement)

    def get_by_runtime_message_id(
        self,
        runtime_message_id: UUID,
        *,
        event_type: OutboxEventType | str = OutboxEventType.MESSAGE_PENDING_COORDINATION,
    ) -> OutboxEvent | None:
        event_type_value = (
            event_type.value if isinstance(event_type, OutboxEventType) else event_type
        )
        statement = select(OutboxEvent).where(
            OutboxEvent.runtime_message_id == runtime_message_id,
            OutboxEvent.event_type == event_type_value,
        )
        return self._session.scalar(statement)

    def list_pending_chat_ids_with_oldest_work(self) -> list[tuple[int, datetime]]:
        """Return chat_ids that have pending outbox work with their oldest created_at."""
        now = utcnow()
        statement = (
            select(
                OutboxEvent.chat_id,
                func.min(OutboxEvent.created_at).label("oldest"),
            )
            .where(
                OutboxEvent.status == OutboxEventStatus.PENDING,
                OutboxEvent.available_at <= now,
            )
            .group_by(OutboxEvent.chat_id)
            .order_by(func.min(OutboxEvent.created_at), OutboxEvent.chat_id)
        )
        rows = self._session.execute(statement).all()
        return [(int(row.chat_id), row.oldest) for row in rows]

    def _active_claim_exists(self, *, claim_token: UUID) -> Exists:
        return exists(
            select(ConversationClaim.chat_id).where(
                ConversationClaim.chat_id == OutboxEvent.chat_id,
                ConversationClaim.status == ClaimStatus.CLAIMED,
                ConversationClaim.claim_token == claim_token,
            )
        )

    def mark_published_for_message(
        self,
        *,
        runtime_message_id: UUID,
        claim_token: UUID | None = None,
        event_type: OutboxEventType | str = OutboxEventType.MESSAGE_PENDING_COORDINATION,
    ) -> OutboxEvent | None:
        event_type_value = (
            event_type.value if isinstance(event_type, OutboxEventType) else event_type
        )
        conditions = [
            OutboxEvent.runtime_message_id == runtime_message_id,
            OutboxEvent.event_type == event_type_value,
            OutboxEvent.status.in_(
                (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
            ),
        ]
        if claim_token is not None:
            conditions.append(self._active_claim_exists(claim_token=claim_token))

        statement = (
            update(OutboxEvent)
            .where(*conditions)
            .values(
                status=OutboxEventStatus.PUBLISHED,
                published_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(OutboxEvent)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def record_failure_for_message(
        self,
        *,
        runtime_message_id: UUID,
        claim_token: UUID,
        error_message: str,
        next_available_at: datetime,
        event_type: OutboxEventType | str = OutboxEventType.MESSAGE_PENDING_COORDINATION,
    ) -> OutboxEvent | None:
        """Retryable failure. No-op unless claim_token owns the active conversation claim."""
        event_type_value = (
            event_type.value if isinstance(event_type, OutboxEventType) else event_type
        )
        statement = (
            update(OutboxEvent)
            .where(
                OutboxEvent.runtime_message_id == runtime_message_id,
                OutboxEvent.event_type == event_type_value,
                OutboxEvent.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                ),
                self._active_claim_exists(claim_token=claim_token),
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
        return self._session.execute(statement).scalar_one_or_none()

    def mark_failed_for_message(
        self,
        *,
        runtime_message_id: UUID,
        claim_token: UUID,
        error_message: str,
        event_type: OutboxEventType | str = OutboxEventType.MESSAGE_PENDING_COORDINATION,
    ) -> OutboxEvent | None:
        """Permanent failure. No-op unless claim_token owns the active conversation claim."""
        event_type_value = (
            event_type.value if isinstance(event_type, OutboxEventType) else event_type
        )
        statement = (
            update(OutboxEvent)
            .where(
                OutboxEvent.runtime_message_id == runtime_message_id,
                OutboxEvent.event_type == event_type_value,
                OutboxEvent.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                ),
                self._active_claim_exists(claim_token=claim_token),
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
        return self._session.execute(statement).scalar_one_or_none()

    def get_head_unresolved_for_chat(self, *, chat_id: int) -> OutboxEvent | None:
        """Earliest unresolved (pending/processing) outbox event for a chat by message_id."""
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.chat_id == chat_id,
                OutboxEvent.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                ),
            )
            .order_by(OutboxEvent.message_id.asc(), OutboxEvent.created_at.asc())
            .limit(1)
        )
        return self._session.scalar(statement)

    def list_unresolved_for_chat_by_type(
        self,
        *,
        chat_id: int,
        event_type: OutboxEventType | str,
        limit: int,
    ) -> list[OutboxEvent]:
        event_type_value = (
            event_type.value if isinstance(event_type, OutboxEventType) else event_type
        )
        statement = (
            select(OutboxEvent)
            .where(
                OutboxEvent.chat_id == chat_id,
                OutboxEvent.event_type == event_type_value,
                OutboxEvent.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                ),
            )
            .order_by(OutboxEvent.message_id.asc(), OutboxEvent.created_at.asc())
            .limit(limit)
            .with_for_update()
        )
        return list(self._session.scalars(statement).all())

    def schedule_dispatch_retry_for_head(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        error_message: str,
        next_available_at: datetime,
    ) -> OutboxEvent | None:
        """Backoff the head unresolved outbox event under the active claim token.

        Used when conversation claim succeeded but broker enqueue failed. Events are
        not leased by claim selection; this still bumps attempt_count and available_at
        so redispatch respects retry policy.
        """
        head = self.get_head_unresolved_for_chat(chat_id=chat_id)
        if head is None:
            return None
        return self.record_failure_for_message(
            runtime_message_id=head.runtime_message_id,
            claim_token=claim_token,
            error_message=error_message,
            next_available_at=next_available_at,
            event_type=head.event_type,
        )

    def recover_expired_leases(self, *, lease_timeout: timedelta) -> int:
        expired_before = utcnow() - lease_timeout
        statement = (
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
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)

    def claim_pending_for_chat(
        self,
        *,
        chat_id: int,
        lease_owner: str,
        lease_timeout: timedelta,
        limit: int,
    ) -> list[OutboxEvent]:
        now = utcnow()
        expired_before = now - lease_timeout
        locked_ids_statement = (
            select(OutboxEvent.id)
            .where(
                OutboxEvent.chat_id == chat_id,
                or_(
                    and_(
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                        OutboxEvent.available_at <= now,
                    ),
                    and_(
                        OutboxEvent.status == OutboxEventStatus.PROCESSING,
                        OutboxEvent.locked_at < expired_before,
                    ),
                ),
            )
            .order_by(OutboxEvent.message_id.asc(), OutboxEvent.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        locked_ids = list(self._session.scalars(locked_ids_statement).all())
        if not locked_ids:
            return []

        update_statement = (
            update(OutboxEvent)
            .where(OutboxEvent.id.in_(locked_ids))
            .values(
                status=OutboxEventStatus.PROCESSING,
                locked_at=now,
                locked_by=lease_owner,
            )
            .returning(OutboxEvent)
        )
        claimed_by_id = {
            event.id: event
            for event in self._session.execute(update_statement).scalars().all()
        }
        return [claimed_by_id[event_id] for event_id in locked_ids if event_id in claimed_by_id]
