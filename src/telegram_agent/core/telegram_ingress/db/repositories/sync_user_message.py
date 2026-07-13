from typing import cast
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from telegram_agent.core.telegram_ingress.common.types import ConversationStatus
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage


class SyncSqlAlchemyUserMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def mark_dispatch_status_for_event(
        self,
        *,
        dispatch_event_id: UUID,
        status: ConversationStatus,
    ) -> int:
        statement = (
            update(UserMessage)
            .where(
                UserMessage.dispatch_event_id == dispatch_event_id,
                UserMessage.conversation_status == ConversationStatus.ENQUEUED,
            )
            .values(conversation_status=status)
        )
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)
