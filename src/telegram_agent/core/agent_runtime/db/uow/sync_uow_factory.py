from collections.abc import Iterator
from contextlib import contextmanager

from telegram_agent.core.agent_runtime.db.sync_session import SyncSessionLocal
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)


@contextmanager
def sync_agent_runtime_uow_factory() -> Iterator[SyncSqlAlchemyAgentRuntimeUnitOfWork]:
    with SyncSessionLocal() as session:
        with SyncSqlAlchemyAgentRuntimeUnitOfWork(session) as uow:
            yield uow
