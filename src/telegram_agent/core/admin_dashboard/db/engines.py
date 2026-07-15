"""Multi-database async engine/session management (read-only usage)."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from telegram_agent.core.admin_dashboard.common.settings import Settings
from telegram_agent.core.admin_dashboard.common.types import DbName
from telegram_agent.core.common.db.session_factory import normalize_async_db_url


@dataclass(frozen=True, slots=True)
class DatabaseBundle:
    name: DbName
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]


class DashboardDatabases:
    """Owns one engine per service database for the process lifetime."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bundles: dict[DbName, DatabaseBundle] = {}

    def start(self) -> None:
        self._bundles = {
            DbName.INGRESS: self._make_bundle(
                DbName.INGRESS,
                self._settings.telegram_ingress_ro_database_url,
            ),
            DbName.CONTENT_PROCESSING: self._make_bundle(
                DbName.CONTENT_PROCESSING,
                self._settings.content_processing_ro_database_url,
            ),
            DbName.AGENT_RUNTIME: self._make_bundle(
                DbName.AGENT_RUNTIME,
                self._settings.agent_runtime_ro_database_url,
            ),
            DbName.AUTH: self._make_bundle(
                DbName.AUTH,
                self._settings.telegram_auth_ro_database_url,
            ),
        }

    def _make_bundle(self, name: DbName, url: str) -> DatabaseBundle:
        engine = create_async_engine(
            normalize_async_db_url(url),
            echo=False,
            future=True,
            pool_size=self._settings.db_pool_size,
            max_overflow=self._settings.db_pool_max_overflow,
            pool_pre_ping=True,
            connect_args={
                # asyncpg connection kwargs
                "timeout": self._settings.db_connect_timeout_seconds,
                "command_timeout": self._settings.db_query_timeout_seconds,
                "server_settings": {
                    "default_transaction_read_only": "on",
                },
            },
        )
        factory = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
            autoflush=False,
            autocommit=False,
        )
        return DatabaseBundle(name=name, engine=engine, session_factory=factory)

    def get(self, name: DbName) -> DatabaseBundle:
        if name not in self._bundles:
            raise RuntimeError(f"Database bundle {name} is not started")
        return self._bundles[name]

    @asynccontextmanager
    async def session(self, name: DbName) -> AsyncIterator[AsyncSession]:
        """Yield a session that never commits.

        Concurrent awaitables must not share one AsyncSession — callers should
        use separate sessions or run queries sequentially.
        """
        factory = self.get(name).session_factory
        session = factory()
        try:
            yield session
        finally:
            # close() rolls back any open transaction; avoid rollback while the
            # session is still provisioning a connection (raises InvalidRequestError).
            await session.close()

    async def dispose(self) -> None:
        for bundle in self._bundles.values():
            await bundle.engine.dispose()
        self._bundles.clear()

    async def ping(self, name: DbName) -> None:
        from sqlalchemy import text

        async with self.session(name) as session:
            await session.execute(text("SELECT 1"))
