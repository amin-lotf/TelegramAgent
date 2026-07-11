from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.db.repositories.sync_job import SyncSqlAlchemyJobRepository
from telegram_agent.core.content_processing.db.repositories.sync_outbox import SyncSqlAlchemyOutboxRepository


class SyncSqlAlchemyContentProcessingUnitOfWork:
    def __init__(self, session: Session):
        self._session = session
        self.jobs = SyncSqlAlchemyJobRepository(session)
        self.outbox_events = SyncSqlAlchemyOutboxRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def flush(self) -> None:
        self._session.flush()

    def __enter__(self) -> "SyncSqlAlchemyContentProcessingUnitOfWork":
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
