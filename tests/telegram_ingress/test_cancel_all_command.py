from __future__ import annotations

import pytest
from sqlalchemy import select

from telegram_agent.core.telegram_ingress.common.commands import (
    CreateUserMessageCommand,
)
from telegram_agent.core.telegram_ingress.common.types import (
    ConversationStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import (
    ConversationOutboxEvent,
)
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage
from telegram_agent.core.telegram_ingress.services.async_cancel_all_command import (
    AsyncCancelAllCommandService,
)

pytestmark = pytest.mark.asyncio


async def test_cancel_all_command_and_outbox_are_persisted_idempotently(
    ingress_uow_factory,
    ingress_sessionmaker,
) -> None:
    command = CreateUserMessageCommand(
        update_id=2020,
        telegram_user_id=7,
        chat_id=100,
        message_id=20,
        text="/cancel_all",
    )
    service = AsyncCancelAllCommandService(uow_factory=ingress_uow_factory)

    await service.accept(command)
    await service.accept(command)

    async with ingress_sessionmaker() as session:
        messages = list((await session.scalars(select(UserMessage))).all())
        events = list(
            (await session.scalars(select(ConversationOutboxEvent))).all()
        )

    assert len(messages) == 1
    assert len(events) == 1
    assert messages[0].conversation_status == ConversationStatus.ENQUEUED
    assert messages[0].dispatch_event_id == events[0].id
    assert (
        events[0].event_type
        == OutboxEventType.CANCEL_ALL_SECONDARY_TASKS_REQUESTED
    )
    assert events[0].payload == {
        "telegram_user_id": 7,
        "chat_id": 100,
        "command_message_id": 20,
    }
