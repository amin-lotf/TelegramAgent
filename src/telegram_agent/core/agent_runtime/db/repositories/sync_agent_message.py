from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from telegram_agent.core.agent_runtime.common.types import AgentMessageRole
from telegram_agent.core.agent_runtime.db.models.runtime import AgentMessage


class SyncSqlAlchemyAgentMessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, message: AgentMessage) -> AgentMessage:
        self._session.add(message)
        return message

    def get_by_id(self, message_id: UUID) -> AgentMessage | None:
        return self._session.get(AgentMessage, message_id)

    def get_by_group_and_role(
        self,
        *,
        group_id: UUID,
        role: AgentMessageRole,
    ) -> AgentMessage | None:
        statement = select(AgentMessage).where(
            AgentMessage.group_id == group_id,
            AgentMessage.role == role,
        )
        return self._session.scalar(statement)
