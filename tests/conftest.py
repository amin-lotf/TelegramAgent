from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import psycopg2.sql
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from telegram_agent.core.common.db.session_factory import (  # noqa: E402
    normalize_async_db_url,
    normalize_sync_db_url,
)
from telegram_agent.core.telegram_auth.db.models.telegram_user import TelegramUser  # noqa: E402
from telegram_agent.core.telegram_auth.db.uow.async_telegram_auth import (  # noqa: E402
    SqlAlchemyTelegramAuthUnitOfWork,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.telegram_ingress.db.models.user_message import (  # noqa: E402
    Attachment,
    UserMessage,
)
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (  # noqa: E402
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)


AUTH_TABLES = ("telegram_users",)
INGRESS_TABLES = ("voice_attachments", "attachments", "user_messages")


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_command(command_args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command_args,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def _wait_for_postgres(admin_url: str, timeout_seconds: float = 45.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            with psycopg2.connect(admin_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                    cursor.fetchone()
                return
        except Exception as exc:  # pragma: no cover - exercised only on startup races
            last_error = exc
            time.sleep(1)

    raise RuntimeError("Timed out waiting for the test Postgres instance to become ready") from last_error


def _create_database(admin_url: str, database_name: str) -> None:
    connection = psycopg2.connect(admin_url)
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                psycopg2.sql.SQL("CREATE DATABASE {}").format(
                    psycopg2.sql.Identifier(database_name)
                )
            )
    finally:
        connection.close()


def _drop_database(admin_url: str, database_name: str) -> None:
    connection = psycopg2.connect(admin_url)
    connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            cursor.execute(
                psycopg2.sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    psycopg2.sql.Identifier(database_name)
                )
            )
    finally:
        connection.close()


def _run_migrations(section_name: str, database_url: str) -> None:
    config = Config(str(ROOT / "alembic.ini"), ini_section=section_name)
    config.set_main_option("sqlalchemy.url", normalize_sync_db_url(database_url))
    command.upgrade(config, "head")


async def _truncate_tables(engine: AsyncEngine, table_names: tuple[str, ...]) -> None:
    joined = ", ".join(table_names)
    async with engine.begin() as connection:
        await connection.execute(text(f"TRUNCATE TABLE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def postgres_admin_url() -> str:
    external_url = os.environ.get("TELEGRAM_AGENT_TEST_POSTGRES_URL")
    if external_url:
        normalized = normalize_sync_db_url(external_url)
        _wait_for_postgres(normalized)
        return normalized

    port = _find_free_port()
    container_name = f"telegram-agent-test-postgres-{uuid4().hex[:8]}"
    image = os.environ.get("TELEGRAM_AGENT_TEST_POSTGRES_IMAGE", "postgres:16-alpine")

    try:
        _run_command(
            [
                "docker",
                "run",
                "--detach",
                "--rm",
                "--name",
                container_name,
                "--publish",
                f"127.0.0.1:{port}:5432",
                "--env",
                "POSTGRES_USER=postgres",
                "--env",
                "POSTGRES_PASSWORD=postgres",
                "--env",
                "POSTGRES_DB=postgres",
                image,
            ]
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - depends on host setup
        stderr = exc.stderr.strip()
        raise RuntimeError(
            "Unable to start the Postgres test container. "
            "Set TELEGRAM_AGENT_TEST_POSTGRES_URL to an existing non-production Postgres instance "
            "or run the tests where Docker is available."
        ) from RuntimeError(stderr)

    admin_url = f"postgresql://postgres:postgres@127.0.0.1:{port}/postgres"
    _wait_for_postgres(admin_url)

    try:
        yield admin_url
    finally:
        subprocess.run(
            ["docker", "rm", "--force", container_name],
            check=False,
            capture_output=True,
            text=True,
        )


@pytest.fixture(scope="session")
def database_urls(postgres_admin_url: str) -> dict[str, str]:
    auth_database = f"telegram_auth_test_{uuid4().hex[:8]}"
    ingress_database = f"telegram_ingress_test_{uuid4().hex[:8]}"
    database_names = {
        "auth": auth_database,
        "ingress": ingress_database,
    }

    try:
        for database_name in database_names.values():
            _create_database(postgres_admin_url, database_name)

        auth_url = postgres_admin_url.rsplit("/", 1)[0] + f"/{auth_database}"
        ingress_url = postgres_admin_url.rsplit("/", 1)[0] + f"/{ingress_database}"

        _run_migrations("telegram_auth", auth_url)
        _run_migrations("telegram_ingress", ingress_url)

        yield {
            "auth": normalize_async_db_url(auth_url),
            "ingress": normalize_async_db_url(ingress_url),
        }
    finally:
        for database_name in reversed(tuple(database_names.values())):
            _drop_database(postgres_admin_url, database_name)


@pytest_asyncio.fixture
async def auth_engine(database_urls: dict[str, str]) -> AsyncEngine:
    engine = create_async_engine(database_urls["auth"], future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def ingress_engine(database_urls: dict[str, str]) -> AsyncEngine:
    engine = create_async_engine(database_urls["ingress"], future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def auth_sessionmaker(
    auth_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    await _truncate_tables(auth_engine, AUTH_TABLES)
    yield async_sessionmaker(
        auth_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    await _truncate_tables(auth_engine, AUTH_TABLES)


@pytest_asyncio.fixture
async def ingress_sessionmaker(
    ingress_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    await _truncate_tables(ingress_engine, INGRESS_TABLES)
    yield async_sessionmaker(
        ingress_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    await _truncate_tables(ingress_engine, INGRESS_TABLES)


@pytest_asyncio.fixture
async def auth_session(
    auth_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncSession:
    async with auth_sessionmaker() as session:
        yield session


@pytest_asyncio.fixture
async def ingress_session(
    ingress_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncSession:
    async with ingress_sessionmaker() as session:
        yield session


@pytest.fixture
def auth_uow_factory(auth_sessionmaker: async_sessionmaker[AsyncSession]):
    @asynccontextmanager
    async def _factory() -> Any:
        async with auth_sessionmaker() as session:
            async with SqlAlchemyTelegramAuthUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def ingress_uow_factory(ingress_sessionmaker: async_sessionmaker[AsyncSession]):
    @asynccontextmanager
    async def _factory() -> Any:
        async with ingress_sessionmaker() as session:
            async with AsyncSqlAlchemyTelegramIngressUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def telegram_verify_payload() -> dict[str, Any]:
    return {
        "telegram_user_id": 100200300,
        "chat_id": 400500600,
        "password": "open-sesame",
        "username": "verified_user",
        "first_name": "Verified",
        "last_name": "User",
        "is_bot": False,
        "language_code": "en",
    }


@pytest.fixture
def telegram_message_payload() -> dict[str, Any]:
    return {
        "telegram_user_id": 555000111,
        "chat_id": 777888999,
        "message_id": 42,
        "update_id": 4242,
        "first_name": "Ingress",
        "last_name": "User",
        "username": "ingress_user",
        "reply_to_message_id": 41,
        "text": "Need help with the latest update",
        "caption": None,
        "attachment": None,
    }


@pytest.fixture
def auth_user_factory(auth_sessionmaker: async_sessionmaker[AsyncSession]):
    async def _create_user(**overrides: Any) -> TelegramUser:
        values = {
            "telegram_user_id": 900100200,
            "chat_id": 1200340056,
            "username": "existing_user",
            "first_name": "Existing",
            "last_name": "User",
            "is_bot": False,
            "language_code": "en",
            "is_active": True,
        }
        values.update(overrides)

        async with auth_sessionmaker() as session:
            user = TelegramUser(**values)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return _create_user


@pytest.fixture
def ingress_message_factory(ingress_sessionmaker: async_sessionmaker[AsyncSession]):
    async def _create_message(
        *,
        attachment_type: TelegramAttachmentType | None = None,
        attachment_file_id: str = "voice-file-001",
        attachment_file_unique_id: str | None = "voice-unique-001",
        **overrides: Any,
    ) -> UserMessage:
        values = {
            "telegram_user_id": 555000111,
            "chat_id": 777888999,
            "message_id": 42,
            "update_id": 4242,
            "reply_message_id": 41,
            "text": "Need help with the latest update",
        }
        values.update(overrides)

        async with ingress_sessionmaker() as session:
            user_message = UserMessage(**values)
            if attachment_type is not None:
                user_message.attachment = Attachment(
                    type=attachment_type,
                    file_id=attachment_file_id,
                    file_unique_id=attachment_file_unique_id,
                )
            session.add(user_message)
            await session.commit()
            await session.refresh(user_message)
            return user_message

    return _create_message
