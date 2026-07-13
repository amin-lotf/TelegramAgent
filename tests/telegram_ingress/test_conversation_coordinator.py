from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.telegram_ingress.common.types import (
    AttachmentStatus,
    ConversationStatus,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import (
    AsyncSqlAlchemyUserMessageRepository,
)
from telegram_agent.core.telegram_ingress.services.conversation_coordinator import (
    ConversationCoordinator,
)

pytestmark = pytest.mark.asyncio


async def test_enqueues_all_pending_messages_in_message_order(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    later = await ingress_message_factory(
        message_id=20,
        update_id=2020,
        text="later",
    )
    earlier = await ingress_message_factory(
        message_id=10,
        update_id=1010,
        text="earlier",
    )

    result = await ConversationCoordinator(ingress_uow_factory).coordinate(
        earlier.chat_id
    )

    async with ingress_sessionmaker() as session:
        events = list(
            (
                await session.scalars(
                    select(ConversationOutboxEvent)
                    .where(ConversationOutboxEvent.chat_id == earlier.chat_id)
                )
            ).all()
        )
        persisted_earlier = await session.get(UserMessage, earlier.id)
        persisted_later = await session.get(UserMessage, later.id)

    assert result.message_count == 2
    assert result.outbox_event_id is not None
    assert len(events) == 1
    assert [item["message_id"] for item in events[0].payload["messages"]] == [10, 20]
    assert persisted_earlier is not None
    assert persisted_later is not None
    assert persisted_earlier.conversation_status == ConversationStatus.ENQUEUED
    assert persisted_later.conversation_status == ConversationStatus.ENQUEUED
    assert persisted_earlier.dispatch_event_id == events[0].id
    assert persisted_later.dispatch_event_id == events[0].id


async def test_pending_voice_blocks_entire_chat_batch(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    voice = await ingress_message_factory(
        message_id=10,
        update_id=1010,
        text=None,
        attachment_type=TelegramAttachmentType.VOICE,
    )
    text_message = await ingress_message_factory(
        message_id=20,
        update_id=2020,
        text="must wait for voice",
    )

    result = await ConversationCoordinator(ingress_uow_factory).coordinate(
        voice.chat_id
    )

    async with ingress_sessionmaker() as session:
        event_count = len(
            (
                await session.scalars(select(ConversationOutboxEvent.id))
            ).all()
        )
        persisted_voice = await session.get(UserMessage, voice.id)
        persisted_text = await session.get(UserMessage, text_message.id)

    assert result.blocked is True
    assert result.message_count == 0
    assert event_count == 0
    assert persisted_voice is not None
    assert persisted_text is not None
    assert persisted_voice.conversation_status == ConversationStatus.PENDING
    assert persisted_text.conversation_status == ConversationStatus.PENDING


async def test_terminal_voice_allows_batch_while_video_is_processing(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    voice = await ingress_message_factory(
        message_id=10,
        update_id=1010,
        text=None,
        attachment_type=TelegramAttachmentType.VOICE,
    )
    video = await ingress_message_factory(
        message_id=20,
        update_id=2020,
        text="video caption",
        attachment_type=TelegramAttachmentType.VIDEO,
    )
    await _set_attachment_status(
        ingress_sessionmaker,
        voice.id,
        AttachmentStatus.FAILED,
    )
    await _set_attachment_status(
        ingress_sessionmaker,
        video.id,
        AttachmentStatus.PROCESSING,
    )

    result = await ConversationCoordinator(ingress_uow_factory).coordinate(
        voice.chat_id
    )

    async with ingress_sessionmaker() as session:
        event = (
            await session.scalars(select(ConversationOutboxEvent))
        ).one()

    assert result.blocked is False
    assert result.message_count == 2
    assert [item["message_id"] for item in event.payload["messages"]] == [10, 20]
    assert event.payload["messages"][1]["attachment"]["status"] == "processing"


async def test_concurrent_coordinators_create_one_non_overlapping_batch(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        message_id=10,
        update_id=1010,
        text="only once",
    )
    first = ConversationCoordinator(ingress_uow_factory)
    second = ConversationCoordinator(ingress_uow_factory)

    results = await asyncio.gather(
        first.coordinate(message.chat_id),
        second.coordinate(message.chat_id),
    )

    async with ingress_sessionmaker() as session:
        events = list((await session.scalars(select(ConversationOutboxEvent))).all())

    assert len(events) == 1
    assert sorted(result.message_count for result in results) == [0, 1]


async def _set_attachment_status(
    sessionmaker_,
    message_id,
    status: AttachmentStatus,
) -> None:
    async with sessionmaker_() as session:
        repository = AsyncSqlAlchemyUserMessageRepository(session)
        message = await repository.get_by_id(message_id)
        assert message is not None
        assert message.attachment is not None
        message.attachment.status = status
        await session.commit()
