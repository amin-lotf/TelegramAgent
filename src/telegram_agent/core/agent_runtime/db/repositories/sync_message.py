from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session, joinedload

from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    MessageIntent,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import RuntimeMessage
from telegram_agent.core.common.utils import utcnow


class SyncSqlAlchemyRuntimeMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, message_id: UUID) -> RuntimeMessage | None:
        statement = (
            select(RuntimeMessage)
            .where(RuntimeMessage.id == message_id)
            .options(joinedload(RuntimeMessage.group))
        )
        return self._session.scalars(statement).unique().one_or_none()

    def list_pending_for_chat(
        self,
        *,
        chat_id: int,
        limit: int,
    ) -> list[RuntimeMessage]:
        statement = (
            select(RuntimeMessage)
            .where(
                RuntimeMessage.chat_id == chat_id,
                RuntimeMessage.coordination_status == CoordinationStatus.PENDING,
            )
            .order_by(RuntimeMessage.message_id.asc(), RuntimeMessage.created_at.asc())
            .limit(limit)
            .with_for_update()
        )
        return list(self._session.scalars(statement).all())

    def list_recent_before(
        self,
        *,
        chat_id: int,
        before_message_id: int,
        limit: int,
    ) -> list[RuntimeMessage]:
        """Return up to ``limit`` successfully grouped messages before ``before_message_id``.

        Selection uses descending ``message_id`` for efficiency, then reverses so the
        returned list is chronological (oldest → newest). Vague and pending messages
        are excluded so they cannot influence later grouping decisions.
        """
        statement = (
            select(RuntimeMessage)
            .where(
                RuntimeMessage.chat_id == chat_id,
                RuntimeMessage.message_id < before_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.GROUPED,
            )
            .options(joinedload(RuntimeMessage.group))
            .order_by(RuntimeMessage.message_id.desc())
            .limit(limit)
        )
        messages = list(self._session.scalars(statement).unique().all())
        messages.reverse()
        return messages

    def list_for_chat_group(
        self,
        *,
        chat_id: int,
        group_id: UUID,
    ) -> list[RuntimeMessage]:
        statement = (
            select(RuntimeMessage)
            .where(
                RuntimeMessage.chat_id == chat_id,
                RuntimeMessage.group_id == group_id,
            )
            .order_by(RuntimeMessage.message_id.asc())
        )
        return list(self._session.scalars(statement).all())

    def mark_coordinating(
        self,
        *,
        runtime_message_id: UUID,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.PENDING,
                RuntimeMessage.status.in_(
                    (
                        RuntimeMessageStatus.RECEIVED,
                        RuntimeMessageStatus.COORDINATING,
                    )
                ),
            )
            .values(status=RuntimeMessageStatus.COORDINATING)
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_grouped(
        self,
        *,
        runtime_message_id: UUID,
        group_id: UUID,
        coordinated_at: datetime | None = None,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.PENDING,
            )
            .values(
                coordination_status=CoordinationStatus.GROUPED,
                status=RuntimeMessageStatus.COORDINATED,
                group_id=group_id,
                coordinated_at=coordinated_at or utcnow(),
            )
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_vague(
        self,
        *,
        runtime_message_id: UUID,
        coordinated_at: datetime | None = None,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.PENDING,
            )
            .values(
                coordination_status=CoordinationStatus.VAGUE,
                status=RuntimeMessageStatus.FAILED,
                group_id=None,
                coordinated_at=coordinated_at or utcnow(),
            )
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_classifying(
        self,
        *,
        runtime_message_id: UUID,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.GROUPED,
                RuntimeMessage.status.in_(
                    (
                        RuntimeMessageStatus.COORDINATED,
                        RuntimeMessageStatus.CLASSIFYING,
                    )
                ),
            )
            .values(status=RuntimeMessageStatus.CLASSIFYING)
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_classified(
        self,
        *,
        runtime_message_id: UUID,
        intent: MessageIntent,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.GROUPED,
                RuntimeMessage.status == RuntimeMessageStatus.CLASSIFYING,
            )
            .values(
                status=RuntimeMessageStatus.CLASSIFIED,
                intent=intent,
            )
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_classification_failed(
        self,
        *,
        runtime_message_id: UUID,
    ) -> RuntimeMessage | None:
        statement = (
            update(RuntimeMessage)
            .where(
                RuntimeMessage.id == runtime_message_id,
                RuntimeMessage.coordination_status == CoordinationStatus.GROUPED,
                RuntimeMessage.status.in_(
                    (
                        RuntimeMessageStatus.COORDINATED,
                        RuntimeMessageStatus.CLASSIFYING,
                    )
                ),
            )
            .values(status=RuntimeMessageStatus.FAILED)
            .returning(RuntimeMessage)
        )
        return self._session.execute(statement).scalar_one_or_none()
