# telegram_agent/common/db/session_factory.py
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker, Session


def normalize_async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url

def normalize_sync_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def create_async_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        normalize_async_db_url(database_url),
        echo=False,
        future=True,
    )

    return async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )

def create_sync_session_factory(database_url: str) -> sessionmaker[Session]:
    engine_sync = create_engine(normalize_sync_db_url(database_url), echo=False, future=True)
    return sessionmaker(
        bind=engine_sync,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False
    )