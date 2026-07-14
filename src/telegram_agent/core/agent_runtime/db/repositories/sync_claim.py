from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from telegram_agent.core.agent_runtime.common.types import ClaimStatus, OutboxEventStatus
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
)
from telegram_agent.core.common.utils import utcnow


@dataclass(frozen=True, slots=True)
class ClaimedConversationRow:
    chat_id: int
    claim_token: UUID


class SyncSqlAlchemyConversationClaimRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def ensure_idle(self, chat_id: int) -> ConversationClaim:
        statement = (
            insert(ConversationClaim)
            .values(
                chat_id=chat_id,
                status=ClaimStatus.IDLE,
                available_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["chat_id"])
            .returning(ConversationClaim)
        )
        result = self._session.execute(statement)
        claim = result.scalar_one_or_none()
        if claim is not None:
            return claim
        return self._session.get(ConversationClaim, chat_id)  # type: ignore[return-value]

    def get(self, chat_id: int) -> ConversationClaim | None:
        return self._session.get(ConversationClaim, chat_id)

    def recover_expired_claims(self, *, lease_timeout: timedelta) -> int:
        expired_before = utcnow() - lease_timeout
        statement = (
            update(ConversationClaim)
            .where(
                ConversationClaim.status == ClaimStatus.CLAIMED,
                ConversationClaim.locked_at < expired_before,
            )
            .values(
                status=ClaimStatus.IDLE,
                claim_token=None,
                locked_at=None,
                locked_by=None,
                available_at=func.now(),
                updated_at=func.now(),
            )
        )
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)

    def claim_available_conversations(
        self,
        *,
        batch_size: int,
        lease_timeout: timedelta,
        process_owner: str | None = None,
    ) -> list[ClaimedConversationRow]:
        """Claim chats whose *earliest* unresolved outbox event is currently eligible.

        A later available message must not make a chat claimable while an earlier
        message is still waiting on retry ``available_at``.
        """
        now = utcnow()
        expired_before = now - lease_timeout

        # Head unresolved event per chat: minimum message_id among pending/processing.
        head_events = (
            select(
                OutboxEvent.chat_id.label("chat_id"),
                OutboxEvent.message_id.label("message_id"),
                OutboxEvent.available_at.label("available_at"),
                OutboxEvent.status.label("status"),
                OutboxEvent.created_at.label("created_at"),
                OutboxEvent.locked_at.label("locked_at"),
            )
            .distinct(OutboxEvent.chat_id)
            .where(
                OutboxEvent.status.in_(
                    (OutboxEventStatus.PENDING, OutboxEventStatus.PROCESSING)
                )
            )
            .order_by(
                OutboxEvent.chat_id.asc(),
                OutboxEvent.message_id.asc(),
                OutboxEvent.created_at.asc(),
            )
            .subquery()
        )

        head_eligible = or_(
            and_(
                head_events.c.status == OutboxEventStatus.PENDING,
                head_events.c.available_at <= now,
            ),
            and_(
                head_events.c.status == OutboxEventStatus.PROCESSING,
                head_events.c.locked_at.is_not(None),
                head_events.c.locked_at < expired_before,
            ),
        )

        claim_eligible = or_(
            and_(
                ConversationClaim.status == ClaimStatus.IDLE,
                ConversationClaim.available_at <= now,
            ),
            and_(
                ConversationClaim.status == ClaimStatus.CLAIMED,
                ConversationClaim.locked_at < expired_before,
            ),
        )

        locked_chat_ids_statement = (
            select(ConversationClaim.chat_id)
            .join(
                head_events,
                head_events.c.chat_id == ConversationClaim.chat_id,
            )
            .where(
                head_eligible,
                claim_eligible,
            )
            .order_by(
                head_events.c.created_at.asc(),
                ConversationClaim.chat_id.asc(),
            )
            .limit(batch_size)
            .with_for_update(of=ConversationClaim, skip_locked=True)
        )
        chat_ids = list(self._session.scalars(locked_chat_ids_statement).all())
        if not chat_ids:
            return []

        claimed: list[ClaimedConversationRow] = []
        for chat_id in chat_ids:
            claim_token = uuid4()
            statement = (
                update(ConversationClaim)
                .where(ConversationClaim.chat_id == chat_id)
                .values(
                    status=ClaimStatus.CLAIMED,
                    claim_token=claim_token,
                    locked_at=now,
                    locked_by=process_owner,
                    updated_at=now,
                )
                .returning(ConversationClaim)
            )
            claim = self._session.execute(statement).scalar_one_or_none()
            if claim is not None and claim.claim_token is not None:
                claimed.append(
                    ClaimedConversationRow(
                        chat_id=claim.chat_id,
                        claim_token=claim.claim_token,
                    )
                )
        return claimed

    def verify_claim(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> bool:
        claim = self.get(chat_id)
        if claim is None:
            return False
        if claim.status != ClaimStatus.CLAIMED:
            return False
        if claim.claim_token != claim_token:
            return False
        if claim.locked_at is None:
            return False
        return claim.locked_at >= utcnow() - lease_timeout

    def renew(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> ConversationClaim | None:
        now = utcnow()
        expired_before = now - lease_timeout
        statement = (
            update(ConversationClaim)
            .where(
                ConversationClaim.chat_id == chat_id,
                ConversationClaim.status == ClaimStatus.CLAIMED,
                ConversationClaim.claim_token == claim_token,
                ConversationClaim.locked_at >= expired_before,
            )
            .values(
                locked_at=now,
                updated_at=now,
            )
            .returning(ConversationClaim)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def release(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        available_at: datetime | None = None,
    ) -> ConversationClaim | None:
        statement = (
            update(ConversationClaim)
            .where(
                ConversationClaim.chat_id == chat_id,
                ConversationClaim.status == ClaimStatus.CLAIMED,
                ConversationClaim.claim_token == claim_token,
            )
            .values(
                status=ClaimStatus.IDLE,
                claim_token=None,
                locked_at=None,
                locked_by=None,
                available_at=available_at or utcnow(),
                updated_at=func.now(),
            )
            .returning(ConversationClaim)
        )
        return self._session.execute(statement).scalar_one_or_none()
