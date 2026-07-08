from __future__ import annotations

from datetime import timedelta

import pytest

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_auth.db.repositories.telegram_user import (
    SqlAlchemyTelegramUserRepository,
)


pytestmark = pytest.mark.asyncio


async def test_create_or_update_verified_user_persists_new_user(auth_session) -> None:
    repository = SqlAlchemyTelegramUserRepository(auth_session)

    user = await repository.create_or_update_verified_user(
        telegram_user_id=123456789,
        chat_id=777888999,
        username="new_user",
        first_name="New",
        last_name="User",
        is_bot=False,
        language_code="en",
    )
    await auth_session.commit()

    persisted = await repository.get_by_telegram_user_id(123456789)

    assert persisted is not None
    assert persisted.id == user.id
    assert persisted.chat_id == 777888999
    assert persisted.username == "new_user"
    assert persisted.first_name == "New"
    assert persisted.last_name == "User"
    assert persisted.is_active is True
    assert persisted.language_code == "en"


async def test_create_or_update_verified_user_updates_existing_user(auth_session, auth_user_factory) -> None:
    existing_user = await auth_user_factory(
        telegram_user_id=222333444,
        chat_id=1000,
        username="old_name",
        first_name="Old",
        last_name="Profile",
        language_code="fa",
        is_active=False,
        last_seen_at=utcnow() - timedelta(days=2),
    )

    repository = SqlAlchemyTelegramUserRepository(auth_session)
    updated_user = await repository.create_or_update_verified_user(
        telegram_user_id=222333444,
        chat_id=9000,
        username="new_name",
        first_name="Updated",
        last_name="Profile",
        is_bot=False,
        language_code="en",
    )
    await auth_session.commit()

    reloaded = await repository.get_by_telegram_user_id(222333444)

    assert reloaded is not None
    assert updated_user.id == existing_user.id
    assert reloaded.chat_id == 9000
    assert reloaded.username == "new_name"
    assert reloaded.first_name == "Updated"
    assert reloaded.is_active is True
    assert reloaded.last_seen_at > existing_user.last_seen_at


async def test_is_verified_returns_false_for_inactive_user(auth_session, auth_user_factory) -> None:
    await auth_user_factory(
        telegram_user_id=111222333,
        is_active=False,
    )
    repository = SqlAlchemyTelegramUserRepository(auth_session)

    assert await repository.is_verified(111222333) is False


async def test_update_last_seen_changes_timestamp(auth_session, auth_user_factory) -> None:
    seeded_user = await auth_user_factory(
        telegram_user_id=99887766,
        last_seen_at=utcnow() - timedelta(hours=3),
    )
    repository = SqlAlchemyTelegramUserRepository(auth_session)

    await repository.update_last_seen(99887766)
    await auth_session.commit()
    refreshed_user = await repository.get_by_telegram_user_id(99887766)

    assert refreshed_user is not None
    assert refreshed_user.last_seen_at > seeded_user.last_seen_at


async def test_revoke_user_marks_user_inactive(auth_session, auth_user_factory) -> None:
    await auth_user_factory(
        telegram_user_id=654321987,
        is_active=True,
    )
    repository = SqlAlchemyTelegramUserRepository(auth_session)

    await repository.revoke_user(654321987)
    await auth_session.commit()
    revoked_user = await repository.get_by_telegram_user_id(654321987)

    assert revoked_user is not None
    assert revoked_user.is_active is False
