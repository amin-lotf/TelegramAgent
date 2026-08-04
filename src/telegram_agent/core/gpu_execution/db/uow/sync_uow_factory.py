from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from telegram_agent.core.gpu_execution.db.sync_session import SyncSessionLocal
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import SyncSqlAlchemyGpuExecutionUnitOfWork


@contextmanager
def sync_gpu_execution_uow_factory() -> Iterator[SyncSqlAlchemyGpuExecutionUnitOfWork]:
    with SyncSessionLocal() as session:
        with SyncSqlAlchemyGpuExecutionUnitOfWork(session) as uow:
            yield uow
