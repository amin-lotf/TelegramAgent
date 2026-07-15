from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.security.passwords import hash_password


TEST_PASSWORD = "dashboard-test-password"
TEST_PASSWORD_HASH = hash_password(
    TEST_PASSWORD,
    salt=b"dashboard-v2-test",
)


def build_settings(database_urls: dict[str, str]) -> Settings:
    return Settings(
        telegram_ingress_read_database_url=database_urls["ingress"],
        content_processing_read_database_url=database_urls["content"],
        agent_runtime_read_database_url=database_urls["agent_runtime"],
        telegram_auth_read_database_url=database_urls["auth"],
        admin_username="operator",
        admin_password_hash=TEST_PASSWORD_HASH,
        cursor_secret="dashboard-v2-test-cursor-secret-000000",
        database_pool_size=1,
        database_max_overflow=0,
        listing_chunk_size=10,
        listing_scan_limit=100,
    )


@pytest_asyncio.fixture
async def dashboard_settings(database_urls: dict[str, str]) -> Settings:
    return build_settings(database_urls)


@pytest_asyncio.fixture
async def dashboard_databases(
    dashboard_settings: Settings,
) -> AsyncIterator[ReadDatabaseManager]:
    manager = ReadDatabaseManager.from_settings(dashboard_settings)
    try:
        yield manager
    finally:
        await manager.dispose()
