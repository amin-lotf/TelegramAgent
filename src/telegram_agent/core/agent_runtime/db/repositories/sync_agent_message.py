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

    def get_by_ingress_message_and_role(
        self,
        *,
        ingress_message_id: UUID,
        role: AgentMessageRole,
    ) -> AgentMessage | None:
        statement = select(AgentMessage).where(
            AgentMessage.ingress_message_id == ingress_message_id,
            AgentMessage.role == role,
        )
        return self._session.scalar(statement)
