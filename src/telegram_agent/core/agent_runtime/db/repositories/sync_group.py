from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from telegram_agent.core.agent_runtime.db.models.runtime import ConversationGroup


class SyncSqlAlchemyConversationGroupRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_id(self, group_id: UUID) -> ConversationGroup | None:
        return self._session.get(ConversationGroup, group_id)

    def get_by_chat_and_number(
        self,
        *,
        chat_id: int,
        group_number: int,
    ) -> ConversationGroup | None:
        statement = select(ConversationGroup).where(
            ConversationGroup.chat_id == chat_id,
            ConversationGroup.group_number == group_number,
        )
        return self._session.scalar(statement)

    def allocate_next(self, *, chat_id: int) -> ConversationGroup:
        """Allocate the next sequential group_number for a chat (transactional)."""
        # Lock existing group rows for this chat so concurrent allocators serialize.
        lock_statement = (
            select(ConversationGroup)
            .where(ConversationGroup.chat_id == chat_id)
            .order_by(ConversationGroup.group_number.asc())
            .with_for_update()
        )
        self._session.scalars(lock_statement).all()

        max_number = self._session.scalar(
            select(func.max(ConversationGroup.group_number)).where(
                ConversationGroup.chat_id == chat_id
            )
        )
        next_number = 1 if max_number is None else int(max_number) + 1
        group = ConversationGroup(
            id=uuid4(),
            chat_id=chat_id,
            group_number=next_number,
        )
        self._session.add(group)
        self._session.flush()
        return group
