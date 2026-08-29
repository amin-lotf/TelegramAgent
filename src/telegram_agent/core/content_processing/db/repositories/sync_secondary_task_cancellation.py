from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.cancellation import (
    secondary_task_scope_lock_key,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    SecondaryTaskCancellation,
)


class SyncSqlAlchemySecondaryTaskCancellationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def lock_scope(self, *, telegram_user_id: int, chat_id: int) -> None:
        lock_key = secondary_task_scope_lock_key(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )
        self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    def get_by_idempotency_key(
        self, idempotency_key: str
    ) -> SecondaryTaskCancellation | None:
        return self._session.scalar(
            select(SecondaryTaskCancellation).where(
                SecondaryTaskCancellation.idempotency_key == idempotency_key
            )
        )

    def add(
        self, cancellation: SecondaryTaskCancellation
    ) -> SecondaryTaskCancellation:
        self._session.add(cancellation)
        self._session.flush()
        return cancellation

    def set_matched_active_count(
        self, *, cancellation_id: UUID, matched_active_count: int
    ) -> bool:
        statement = (
            update(SecondaryTaskCancellation)
            .where(SecondaryTaskCancellation.id == cancellation_id)
            .values(matched_active_count=matched_active_count)
            .returning(SecondaryTaskCancellation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def find_covering(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        request_message_id: int,
    ) -> SecondaryTaskCancellation | None:
        return self._session.scalar(
            select(SecondaryTaskCancellation)
            .where(
                SecondaryTaskCancellation.telegram_user_id == telegram_user_id,
                SecondaryTaskCancellation.chat_id == chat_id,
                SecondaryTaskCancellation.cutoff_message_id > request_message_id,
            )
            .order_by(desc(SecondaryTaskCancellation.cutoff_message_id))
            .limit(1)
        )
