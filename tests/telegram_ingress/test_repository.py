from __future__ import annotations

import pytest

from telegram_agent.core.telegram_ingress.common.types import TelegramAttachmentType
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import (
    SqlAlchemyUserMessageRepository,
)


pytestmark = pytest.mark.asyncio


async def test_add_and_get_by_id_returns_attachment(ingress_session) -> None:
    repository = SqlAlchemyUserMessageRepository(ingress_session)

    user_message = await _create_message_with_attachment(repository, ingress_session)
    persisted = await repository.get_by_id(user_message.id)

    assert persisted is not None
    assert persisted.id == user_message.id
    assert persisted.text == "Voice note from Telegram"
    assert persisted.attachment is not None
    assert persisted.attachment.type == TelegramAttachmentType.VOICE
    assert persisted.attachment.file_id == "voice-file-123"


async def test_get_existing_returns_message_by_update_id(
    ingress_session,
    ingress_message_factory,
) -> None:
    seeded_message = await ingress_message_factory(
        chat_id=777888999,
        message_id=50,
        update_id=5000,
        text="Original message",
    )
    repository = SqlAlchemyUserMessageRepository(ingress_session)

    existing = await repository.get_existing(
        update_id=5000,
        chat_id=777888999,
        message_id=51,
    )

    assert existing is not None
    assert existing.id == seeded_message.id


async def test_get_existing_falls_back_to_chat_and_message_id(
    ingress_session,
    ingress_message_factory,
) -> None:
    seeded_message = await ingress_message_factory(
        chat_id=333444555,
        message_id=66,
        update_id=None,
        text="Fallback lookup",
    )
    repository = SqlAlchemyUserMessageRepository(ingress_session)

    existing = await repository.get_existing(
        update_id=None,
        chat_id=333444555,
        message_id=66,
    )

    assert existing is not None
    assert existing.id == seeded_message.id


async def _create_message_with_attachment(repository, session):
    from telegram_agent.core.telegram_ingress.db.models.user_message import Attachment, UserMessage

    user_message = UserMessage(
        telegram_user_id=10101010,
        chat_id=20202020,
        message_id=30303030,
        update_id=40404040,
        reply_message_id=None,
        text="Voice note from Telegram",
    )
    user_message.attachment = Attachment(
        type=TelegramAttachmentType.VOICE,
        file_id="voice-file-123",
        file_unique_id="voice-unique-123",
    )
    repository.add(user_message)
    await session.commit()
    return user_message
