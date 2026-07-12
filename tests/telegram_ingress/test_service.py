from __future__ import annotations

import pytest

from telegram_agent.core.telegram_ingress.common.commands import (
    CreateAttachmentCommand,
    CreateUserMessageCommand,
)
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import (
    AsyncSqlAlchemyUserMessageRepository,
)
from telegram_agent.core.telegram_ingress.services.async_user_message import (
    AsyncUserMessageService,
)
from telegram_agent.core.common.types import TelegramAttachmentType

pytestmark = pytest.mark.asyncio



class StubContentProcessingClient:
    def __init__(self) -> None:
        self.commands = []

    async def process_attachment(self, command) -> None:
        self.commands.append(command)


def _service(uow_factory) -> AsyncUserMessageService:
    return AsyncUserMessageService(
        uow_factory=uow_factory,
        content_processing_client=StubContentProcessingClient(),
    )


async def test_create_user_message_persists_update_id(
    ingress_uow_factory,
    ingress_sessionmaker,
) -> None:
    service = _service(ingress_uow_factory)

    created = await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=555000111,
            chat_id=777888999,
            message_id=42,
            update_id=4242,
            reply_message_id=41,
            text="Need help with the latest update",
        )
    )

    async with ingress_sessionmaker() as session:
        repository = AsyncSqlAlchemyUserMessageRepository(session)
        persisted = await repository.get_by_id(created.id)

    assert persisted is not None
    assert persisted.update_id == 4242
    assert persisted.reply_message_id == 41
    assert persisted.text == "Need help with the latest update"


async def test_create_user_message_returns_existing_message_for_same_update_id(
    ingress_uow_factory,
    ingress_message_factory,
) -> None:
    existing_message = await ingress_message_factory(
        message_id=91,
        update_id=9091,
        text="Already stored",
    )
    service = _service(ingress_uow_factory)

    created = await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=555000111,
            chat_id=777888999,
            message_id=92,
            update_id=9091,
            reply_message_id=None,
            text="Duplicate update",
        )
    )

    assert created.id == existing_message.id


async def test_create_user_message_returns_existing_message_for_same_chat_and_message_id(
    ingress_uow_factory,
    ingress_message_factory,
) -> None:
    existing_message = await ingress_message_factory(
        chat_id=12345000,
        message_id=77,
        update_id=None,
        text="Already stored",
    )
    service = _service(ingress_uow_factory)

    created = await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=555000111,
            chat_id=12345000,
            message_id=77,
            update_id=None,
            reply_message_id=None,
            text="Same message",
        )
    )

    assert created.id == existing_message.id


async def test_create_user_message_persists_attachment(
    ingress_uow_factory,
    ingress_sessionmaker,
) -> None:
    service = _service(ingress_uow_factory)

    created = await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=20202020,
            chat_id=30303030,
            message_id=40404040,
            update_id=50505050,
            reply_message_id=None,
            text=None,
            attachment=CreateAttachmentCommand(
                type=TelegramAttachmentType.VOICE,
                file_id="voice-file-999",
                file_unique_id="voice-unique-999",
            ),
        )
    )

    async with ingress_sessionmaker() as session:
        repository = AsyncSqlAlchemyUserMessageRepository(session)
        persisted = await repository.get_by_id(created.id)

    assert persisted is not None
    assert persisted.attachment is not None
    assert persisted.attachment.type == TelegramAttachmentType.VOICE
    assert persisted.attachment.file_id == "voice-file-999"
