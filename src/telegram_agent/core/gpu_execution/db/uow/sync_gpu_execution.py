from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from telegram_agent.core.gpu_execution.db.repositories.sync_gpu_job import SyncSqlAlchemyGpuJobRepository
from telegram_agent.core.gpu_execution.db.repositories.sync_outbox import SyncSqlAlchemyGpuOutboxRepository


class SyncSqlAlchemyGpuExecutionUnitOfWork:
    def __init__(self, session: Session) -> None:
        self._session = session
        self.jobs = SyncSqlAlchemyGpuJobRepository(session)
        self.outbox_events = SyncSqlAlchemyGpuOutboxRepository(session)

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def __enter__(self) -> "SyncSqlAlchemyGpuExecutionUnitOfWork":
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
