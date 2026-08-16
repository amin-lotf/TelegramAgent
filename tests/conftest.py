from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager, contextmanager
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
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from telegram_agent.core.common.db.session_factory import (  # noqa: E402
    create_sync_session_factory,
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
from telegram_agent.core.telegram_ingress.db.uow.sync_telegram_ingress import (  # noqa: E402
    SyncSqlAlchemyTelegramIngressUnitOfWork,
)
from telegram_agent.core.content_processing.db.models.content_processing import Job  # noqa: E402
from telegram_agent.core.content_processing.db.uow.async_content_processing import (  # noqa: E402
    AsyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (  # noqa: E402
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.async_agent_runtime import (  # noqa: E402
    AsyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (  # noqa: E402
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import (  # noqa: E402
    SyncSqlAlchemyGpuExecutionUnitOfWork,
)


AUTH_TABLES = ("telegram_users",)
INGRESS_TABLES = (
    "attachments",
    "user_messages",
    "conversation_outbox_events",
)
CONTENT_PROCESSING_TABLES = (
    "outbox_events",
    "dubbing_artifacts",
    "dubbing_workflows",
    "translated_segments",
    "translation_batches",
    "subtitle_translations",
    "chunk_embeddings",
    "content_chunks",
    "transcript_segments",
    "transcripts",
    "download_requests",
    "media_assets",
    "telegram_sources",
    "job_completion_expectations",
    "jobs",
)
AGENT_RUNTIME_TABLES = (
    "agent_messages",
    "coordination_outbox_events",
    "runtime_messages",
    "conversation_groups",
    "runtime_batches",
    "conversation_claims",
)
GPU_EXECUTION_TABLES = (
    "gpu_outbox_events",
    "gpu_jobs",
)


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
    # content-processing migrations require the `vector` extension (pgvector).
    image = os.environ.get(
        "TELEGRAM_AGENT_TEST_POSTGRES_IMAGE",
        "pgvector/pgvector:pg16",
    )

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
    content_database = f"content_processing_test_{uuid4().hex[:8]}"
    agent_runtime_database = f"agent_runtime_test_{uuid4().hex[:8]}"
    gpu_execution_database = f"gpu_execution_test_{uuid4().hex[:8]}"
    database_names = {
        "auth": auth_database,
        "ingress": ingress_database,
        "content": content_database,
        "agent_runtime": agent_runtime_database,
        "gpu_execution": gpu_execution_database,
    }

    try:
        for database_name in database_names.values():
            _create_database(postgres_admin_url, database_name)

        auth_url = postgres_admin_url.rsplit("/", 1)[0] + f"/{auth_database}"
        ingress_url = postgres_admin_url.rsplit("/", 1)[0] + f"/{ingress_database}"
        content_url = postgres_admin_url.rsplit("/", 1)[0] + f"/{content_database}"
        agent_runtime_url = (
            postgres_admin_url.rsplit("/", 1)[0] + f"/{agent_runtime_database}"
        )
        gpu_execution_url = (
            postgres_admin_url.rsplit("/", 1)[0] + f"/{gpu_execution_database}"
        )

        _run_migrations("telegram_auth", auth_url)
        _run_migrations("telegram_ingress", ingress_url)
        _run_migrations("content_processing", content_url)
        _run_migrations("agent_runtime", agent_runtime_url)
        _run_migrations("gpu_execution", gpu_execution_url)

        yield {
            "auth": normalize_async_db_url(auth_url),
            "ingress": normalize_async_db_url(ingress_url),
            "ingress_sync": normalize_sync_db_url(ingress_url),
            "content": normalize_async_db_url(content_url),
            "content_sync": normalize_sync_db_url(content_url),
            "agent_runtime": normalize_async_db_url(agent_runtime_url),
            "agent_runtime_sync": normalize_sync_db_url(agent_runtime_url),
            "gpu_execution_sync": normalize_sync_db_url(gpu_execution_url),
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
async def content_engine(database_urls: dict[str, str]) -> AsyncEngine:
    engine = create_async_engine(database_urls["content"], future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def agent_runtime_engine(database_urls: dict[str, str]) -> AsyncEngine:
    engine = create_async_engine(database_urls["agent_runtime"], future=True)
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
async def content_sessionmaker(
    content_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    await _truncate_tables(content_engine, CONTENT_PROCESSING_TABLES)
    yield async_sessionmaker(
        content_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    await _truncate_tables(content_engine, CONTENT_PROCESSING_TABLES)


@pytest_asyncio.fixture
async def agent_runtime_sessionmaker(
    agent_runtime_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    await _truncate_tables(agent_runtime_engine, AGENT_RUNTIME_TABLES)
    yield async_sessionmaker(
        agent_runtime_engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    await _truncate_tables(agent_runtime_engine, AGENT_RUNTIME_TABLES)


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


@pytest_asyncio.fixture
async def content_session(
    content_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncSession:
    async with content_sessionmaker() as session:
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
def content_uow_factory(content_sessionmaker: async_sessionmaker[AsyncSession]):
    @asynccontextmanager
    async def _factory() -> Any:
        async with content_sessionmaker() as session:
            async with AsyncSqlAlchemyContentProcessingUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def agent_runtime_uow_factory(
    agent_runtime_sessionmaker: async_sessionmaker[AsyncSession],
):
    @asynccontextmanager
    async def _factory() -> Any:
        async with agent_runtime_sessionmaker() as session:
            async with AsyncSqlAlchemyAgentRuntimeUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def ingress_sync_sessionmaker(
    database_urls: dict[str, str],
) -> sessionmaker[Session]:
    factory = create_sync_session_factory(database_urls["ingress_sync"])
    table_names = ", ".join(INGRESS_TABLES)
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()


@pytest.fixture
def ingress_sync_uow_factory(
    ingress_sync_sessionmaker: sessionmaker[Session],
):
    @contextmanager
    def _factory() -> Any:
        with ingress_sync_sessionmaker() as session:
            with SyncSqlAlchemyTelegramIngressUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def content_sync_sessionmaker(database_urls: dict[str, str]) -> sessionmaker[Session]:
    factory = create_sync_session_factory(database_urls["content_sync"])
    table_names = ", ".join(CONTENT_PROCESSING_TABLES)
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )


@pytest.fixture
def content_sync_uow_factory(content_sync_sessionmaker: sessionmaker[Session]):
    @contextmanager
    def _factory() -> Any:
        with content_sync_sessionmaker() as session:
            with SyncSqlAlchemyContentProcessingUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def agent_runtime_sync_sessionmaker(
    database_urls: dict[str, str],
) -> sessionmaker[Session]:
    factory = create_sync_session_factory(database_urls["agent_runtime_sync"])
    table_names = ", ".join(AGENT_RUNTIME_TABLES)
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()


@pytest.fixture
def agent_runtime_sync_uow_factory(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
):
    @contextmanager
    def _factory() -> Any:
        with agent_runtime_sync_sessionmaker() as session:
            with SyncSqlAlchemyAgentRuntimeUnitOfWork(session) as uow:
                yield uow

    return _factory


@pytest.fixture
def gpu_execution_sync_sessionmaker(
    database_urls: dict[str, str],
) -> sessionmaker[Session]:
    factory = create_sync_session_factory(database_urls["gpu_execution_sync"])
    table_names = ", ".join(GPU_EXECUTION_TABLES)
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(
            text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
        )
        session.commit()


@pytest.fixture
def gpu_execution_sync_uow_factory(
    gpu_execution_sync_sessionmaker: sessionmaker[Session],
):
    @contextmanager
    def _factory() -> Any:
        with gpu_execution_sync_sessionmaker() as session:
            with SyncSqlAlchemyGpuExecutionUnitOfWork(session) as uow:
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


@pytest.fixture
def content_job_factory(content_sessionmaker: async_sessionmaker[AsyncSession]):
    async def _create_job(**overrides: Any) -> Job:
        from telegram_agent.core.content_processing.common.types import JobKind, JobStatus

        values = {
            "kind": JobKind.TELEGRAM_ATTACHMENT,
            "status": JobStatus.QUEUED,
            "idempotency_key": f"job-{uuid4()}",
            "callback_required": True,
        }
        values.update(overrides)

        async with content_sessionmaker() as session:
            job = Job(**values)
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job

    return _create_job
