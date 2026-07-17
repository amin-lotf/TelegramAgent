from __future__ import annotations

from uuid import UUID

import pytest

from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.telegram_ingress.common.commands import (
    ApplyAttachmentProcessingResultCommand,
)
from telegram_agent.core.telegram_ingress.common.types import (
    AttachmentStatus,
    ConversationStatus,
)
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import (
    AsyncSqlAlchemyUserMessageRepository,
)
from telegram_agent.core.telegram_ingress.services.async_attachment_processing_result import (
    AsyncAttachmentProcessingResultService,
)


pytestmark = pytest.mark.asyncio


class StubConversationCoordinator:
    def __init__(self) -> None:
        self.chat_ids: list[int] = []

    async def coordinate(self, chat_id: int) -> None:
        self.chat_ids.append(chat_id)


def _service(uow_factory) -> AsyncAttachmentProcessingResultService:
    return AsyncAttachmentProcessingResultService(
        uow_factory,
        conversation_coordinator=StubConversationCoordinator(),
    )


async def test_completed_voice_updates_attachment_and_message_text(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        attachment_type=TelegramAttachmentType.VOICE,
        text=None,
    )
    attachment_id = await _get_attachment_id(ingress_sessionmaker, message.id)

    result = await _service(ingress_uow_factory).apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=message.id,
            ingress_attachment_id=attachment_id,
            status=AttachmentProcessingResultStatus.COMPLETED,
            transcribed_text="transcribed voice message",
        )
    )

    async with ingress_sessionmaker() as session:
        persisted = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message.id
        )

    assert result.applied is True
    assert persisted is not None
    assert persisted.attachment is not None
    assert persisted.attachment.status == AttachmentStatus.READY
    assert persisted.text == "transcribed voice message"
    assert persisted.conversation_status == ConversationStatus.PENDING


async def test_completed_document_does_not_replace_message_text(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        attachment_type=TelegramAttachmentType.DOCUMENT,
        text="document caption",
    )
    attachment_id = await _get_attachment_id(ingress_sessionmaker, message.id)

    await _service(ingress_uow_factory).apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=message.id,
            ingress_attachment_id=attachment_id,
            status=AttachmentProcessingResultStatus.COMPLETED,
            transcribed_text="must be ignored",
        )
    )

    async with ingress_sessionmaker() as session:
        persisted = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message.id
        )

    assert persisted is not None
    assert persisted.attachment is not None
    assert persisted.attachment.status == AttachmentStatus.READY
    assert persisted.text == "document caption"


async def test_timed_out_processing_marks_attachment_failed(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        attachment_type=TelegramAttachmentType.VOICE,
        text=None,
    )
    attachment_id = await _get_attachment_id(ingress_sessionmaker, message.id)
    coordinator = StubConversationCoordinator()
    service = AsyncAttachmentProcessingResultService(
        ingress_uow_factory,
        conversation_coordinator=coordinator,
    )

    result = await service.apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=message.id,
            ingress_attachment_id=attachment_id,
            status=AttachmentProcessingResultStatus.TIMED_OUT,
            transcribed_text=None,
        )
    )

    async with ingress_sessionmaker() as session:
        persisted = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message.id
        )

    assert result.applied is True
    assert persisted is not None
    assert persisted.attachment is not None
    assert persisted.attachment.status == AttachmentStatus.FAILED
    assert coordinator.chat_ids == [persisted.chat_id]


async def test_failed_processing_marks_attachment_failed(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        attachment_type=TelegramAttachmentType.VIDEO_NOTE,
        text=None,
    )
    attachment_id = await _get_attachment_id(ingress_sessionmaker, message.id)

    await _service(ingress_uow_factory).apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=message.id,
            ingress_attachment_id=attachment_id,
            status=AttachmentProcessingResultStatus.FAILED,
        )
    )

    async with ingress_sessionmaker() as session:
        persisted = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message.id
        )

    assert persisted is not None
    assert persisted.attachment is not None
    assert persisted.attachment.status == AttachmentStatus.FAILED
    assert persisted.text is None


async def _get_attachment_id(sessionmaker_, message_id: UUID) -> UUID:
    async with sessionmaker_() as session:
        message = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message_id
        )
        assert message is not None
        assert message.attachment is not None
        return message.attachment.id
