from collections.abc import Iterator
from contextlib import contextmanager

from telegram_agent.core.telegram_ingress.db.sync_session import SyncSessionLocal
from telegram_agent.core.telegram_ingress.db.uow.sync_telegram_ingress import SyncSqlAlchemyTelegramIngressUnitOfWork


@contextmanager
def sync_telegram_ingress_uow_factory() -> Iterator[SyncSqlAlchemyTelegramIngressUnitOfWork]:
    with SyncSessionLocal() as session:
        with SyncSqlAlchemyTelegramIngressUnitOfWork(session) as uow:
            yield uow
