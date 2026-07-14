from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from telegram_agent.core.agent_runtime.db.repositories.sync_claim import (
    SyncSqlAlchemyConversationClaimRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.sync_group import (
    SyncSqlAlchemyConversationGroupRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.sync_message import (
    SyncSqlAlchemyRuntimeMessageRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.sync_outbox import (
    SyncSqlAlchemyOutboxRepository,
)


class SyncSqlAlchemyAgentRuntimeUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.messages = SyncSqlAlchemyRuntimeMessageRepository(session)
        self.groups = SyncSqlAlchemyConversationGroupRepository(session)
        self.outbox_events = SyncSqlAlchemyOutboxRepository(session)
        self.conversation_claims = SyncSqlAlchemyConversationClaimRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> "SyncSqlAlchemyAgentRuntimeUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type:
            self.rollback()
        else:
            self.commit()
