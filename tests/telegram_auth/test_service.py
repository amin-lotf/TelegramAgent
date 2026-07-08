from __future__ import annotations

from datetime import timedelta

import pytest

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_auth.common.commands import VerifyTelegramUserCommand
from telegram_agent.core.telegram_auth.common.settings import settings as auth_settings
from telegram_agent.core.telegram_auth.db.repositories.telegram_user import (
    SqlAlchemyTelegramUserRepository,
)
from telegram_agent.core.telegram_auth.security.telegram_user_password import hash_password
from telegram_agent.core.telegram_auth.services.user_authentication import (
    UserAuthenticationService,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def valid_auth_password(monkeypatch: pytest.MonkeyPatch) -> str:
    password = "open-sesame"
    monkeypatch.setattr(auth_settings, "bot_verify_secret", "test-secret")
    monkeypatch.setattr(auth_settings, "bot_verify_hash", hash_password(password))
    return password


async def test_verify_user_persists_user_when_password_matches(
    auth_uow_factory,
    auth_sessionmaker,
    valid_auth_password: str,
) -> None:
    service = UserAuthenticationService(uow_factory=auth_uow_factory)

    verified = await service.verify_user(
        VerifyTelegramUserCommand(
            telegram_user_id=100200300,
            chat_id=400500600,
            password=valid_auth_password,
            username="verified_user",
            first_name="Verified",
            last_name="User",
            is_bot=False,
            language_code="en",
        )
    )

    async with auth_sessionmaker() as session:
        repository = SqlAlchemyTelegramUserRepository(session)
        persisted = await repository.get_by_telegram_user_id(100200300)

    assert verified is True
    assert persisted is not None
    assert persisted.chat_id == 400500600
    assert persisted.username == "verified_user"


async def test_verify_user_returns_false_without_persisting_user(
    auth_uow_factory,
    auth_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_settings, "bot_verify_secret", "test-secret")
    monkeypatch.setattr(auth_settings, "bot_verify_hash", hash_password("correct-password"))
    service = UserAuthenticationService(uow_factory=auth_uow_factory)

    verified = await service.verify_user(
        VerifyTelegramUserCommand(
            telegram_user_id=123123123,
            chat_id=321321321,
            password="wrong-password",
            username="wrong_user",
            is_bot=False,
        )
    )

    async with auth_sessionmaker() as session:
        repository = SqlAlchemyTelegramUserRepository(session)
        persisted = await repository.get_by_telegram_user_id(123123123)

    assert verified is False
    assert persisted is None


async def test_check_user_updates_last_seen_for_verified_user(
    auth_uow_factory,
    auth_sessionmaker,
    auth_user_factory,
) -> None:
    existing_user = await auth_user_factory(
        telegram_user_id=555444333,
        last_seen_at=utcnow() - timedelta(days=1),
    )
    service = UserAuthenticationService(uow_factory=auth_uow_factory)

    verified = await service.check_user(555444333)

    async with auth_sessionmaker() as session:
        repository = SqlAlchemyTelegramUserRepository(session)
        refreshed = await repository.get_by_telegram_user_id(555444333)

    assert verified is True
    assert refreshed is not None
    assert refreshed.last_seen_at > existing_user.last_seen_at


async def test_revoke_user_returns_false_when_user_is_missing(auth_uow_factory) -> None:
    service = UserAuthenticationService(uow_factory=auth_uow_factory)

    assert await service.revoke_user(80808080) is False


async def test_revoke_user_deactivates_existing_user(
    auth_uow_factory,
    auth_sessionmaker,
    auth_user_factory,
) -> None:
    await auth_user_factory(
        telegram_user_id=60606060,
        is_active=True,
    )
    service = UserAuthenticationService(uow_factory=auth_uow_factory)

    revoked = await service.revoke_user(60606060)

    async with auth_sessionmaker() as session:
        repository = SqlAlchemyTelegramUserRepository(session)
        refreshed = await repository.get_by_telegram_user_id(60606060)

    assert revoked is True
    assert refreshed is not None
    assert refreshed.is_active is False
