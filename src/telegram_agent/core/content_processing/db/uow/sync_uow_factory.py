from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from telegram_agent.core.content_processing.db.sync_session import SyncSessionLocal
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


@contextmanager
def sync_content_processing_uow_factory() -> Iterator[SyncSqlAlchemyContentProcessingUnitOfWork]:
    with SyncSessionLocal() as session:
        with SyncSqlAlchemyContentProcessingUnitOfWork(session) as uow:
            yield uow
