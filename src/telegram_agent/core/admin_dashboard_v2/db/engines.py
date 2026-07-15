from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass

from asyncpg import InterfaceError as AsyncpgInterfaceError
from asyncpg import PostgresError as AsyncpgPostgresError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from telegram_agent.core.admin_dashboard_v2.common.exceptions import (
    DataSourceUnavailableError,
)
from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.common.types import (
    DataSourceStatus,
    SourceResult,
)
from telegram_agent.core.common.db.session_factory import normalize_async_db_url


@dataclass(frozen=True, slots=True)
class DatabaseTarget:
    name: str
    engine: AsyncEngine | None


class ReadDatabaseManager:
    def __init__(self, targets: Mapping[str, DatabaseTarget]) -> None:
        self._targets = dict(targets)

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReadDatabaseManager":
        urls = {
            "telegram_ingress": settings.telegram_ingress_read_database_url,
            "content_processing": settings.content_processing_read_database_url,
            "agent_runtime": settings.agent_runtime_read_database_url,
            "telegram_auth": settings.telegram_auth_read_database_url,
        }
        targets: dict[str, DatabaseTarget] = {}
        for name, secret_url in urls.items():
            if secret_url is None:
                targets[name] = DatabaseTarget(name=name, engine=None)
                continue
            url = normalize_async_db_url(secret_url.get_secret_value())
            engine = create_async_engine(
                url,
                pool_pre_ping=True,
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout_seconds,
                connect_args={
                    "timeout": settings.database_connect_timeout_seconds,
                    "server_settings": {
                        "application_name": "telegram-agent-admin-dashboard-v2",
                        "default_transaction_read_only": "on",
                        "statement_timeout": str(settings.database_statement_timeout_ms),
                    },
                },
            )
            targets[name] = DatabaseTarget(name=name, engine=engine)
        return cls(targets)

    @asynccontextmanager
    async def connection(self, source: str) -> AsyncIterator[AsyncConnection]:
        target = self._targets[source]
        if target.engine is None:
            raise DataSourceUnavailableError(source, "Database is not configured")
        try:
            async with target.engine.connect() as connection:
                async with connection.begin():
                    await connection.execute(text("SET TRANSACTION READ ONLY"))
                    yield connection
        except asyncio.TimeoutError as exc:
            raise DataSourceUnavailableError(source, "Database query timed out") from exc
        except ProgrammingError as exc:
            raise DataSourceUnavailableError(source, "Database schema is incompatible") from exc
        except (
            OSError,
            AsyncpgInterfaceError,
            AsyncpgPostgresError,
            OperationalError,
            DBAPIError,
            SQLAlchemyError,
        ) as exc:
            raise DataSourceUnavailableError(source) from exc

    async def dependency_states(self) -> tuple[SourceResult[None], ...]:
        async def check(name: str) -> SourceResult[None]:
            if self._targets[name].engine is None:
                return SourceResult(
                    source=name,
                    status=DataSourceStatus.NOT_CONFIGURED,
                    message="Optional database is not configured",
                )
            try:
                async with self.connection(name) as connection:
                    await connection.execute(text("SELECT 1"))
            except DataSourceUnavailableError as exc:
                status = (
                    DataSourceStatus.TIMED_OUT
                    if "timed out" in exc.reason.lower()
                    else DataSourceStatus.INVALID_SCHEMA
                    if "schema" in exc.reason.lower()
                    else DataSourceStatus.UNAVAILABLE
                )
                return SourceResult(source=name, status=status, message=exc.reason)
            return SourceResult(source=name, status=DataSourceStatus.AVAILABLE)

        return tuple(await asyncio.gather(*(check(name) for name in self._targets)))

    async def dispose(self) -> None:
        await asyncio.gather(
            *(
                target.engine.dispose()
                for target in self._targets.values()
                if target.engine is not None
            )
        )
