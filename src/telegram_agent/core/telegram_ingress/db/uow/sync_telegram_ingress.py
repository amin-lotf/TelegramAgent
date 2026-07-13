from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from telegram_agent.core.telegram_ingress.db.repositories.sync_outbox import SyncSqlAlchemyConversationOutboxRepository
from telegram_agent.core.telegram_ingress.db.repositories.sync_user_message import SyncSqlAlchemyUserMessageRepository


class SyncSqlAlchemyTelegramIngressUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.user_messages = SyncSqlAlchemyUserMessageRepository(session)
        self.outbox_events = SyncSqlAlchemyConversationOutboxRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> "SyncSqlAlchemyTelegramIngressUnitOfWork":
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
