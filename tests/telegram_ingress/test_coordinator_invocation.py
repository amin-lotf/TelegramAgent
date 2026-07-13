from telegram_agent.core.common.exceptions import ContentProcessingUnavailableError
from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.telegram_ingress.common.commands import (
    ApplyAttachmentProcessingResultCommand,
    CreateAttachmentCommand,
    CreateUserMessageCommand,
)
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus
from telegram_agent.core.telegram_ingress.db.repositories.async_user_message import (
    AsyncSqlAlchemyUserMessageRepository,
)
from telegram_agent.core.telegram_ingress.services.async_attachment_processing_result import (
    AsyncAttachmentProcessingResultService,
)
from telegram_agent.core.telegram_ingress.services.async_user_message import (
    AsyncUserMessageService,
)


class RecordingCoordinator:
    def __init__(self, actions: list[str] | None = None) -> None:
        self.chat_ids: list[int] = []
        self._actions = actions

    async def coordinate(self, chat_id: int) -> None:
        self.chat_ids.append(chat_id)
        if self._actions is not None:
            self._actions.append("coordinate")


class RecordingContentProcessingClient:
    def __init__(self, actions: list[str]) -> None:
        self._actions = actions

    async def process_attachment(self, command) -> None:
        self._actions.append("process-attachment")


class UnavailableContentProcessingClient:
    async def process_attachment(self, command) -> None:
        raise ContentProcessingUnavailableError("timed out")


async def test_new_attachment_request_is_prepared_before_coordination(
    ingress_uow_factory,
) -> None:
    actions: list[str] = []
    service = AsyncUserMessageService(
        uow_factory=ingress_uow_factory,
        content_processing_client=RecordingContentProcessingClient(actions),
        conversation_coordinator=RecordingCoordinator(actions),
    )

    await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=123456,
            chat_id=900100,
            message_id=10,
            update_id=1010,
            text="video caption",
            attachment=CreateAttachmentCommand(
                type=TelegramAttachmentType.VIDEO,
                file_id="video-file",
            ),
        )
    )

    assert actions == ["process-attachment", "coordinate"]


async def test_attachment_request_timeout_makes_voice_terminal_before_coordination(
    ingress_uow_factory,
    ingress_sessionmaker,
) -> None:
    coordinator = RecordingCoordinator()
    service = AsyncUserMessageService(
        uow_factory=ingress_uow_factory,
        content_processing_client=UnavailableContentProcessingClient(),
        conversation_coordinator=coordinator,
    )
    result = await service.create_user_message(
        CreateUserMessageCommand(
            telegram_user_id=123456,
            chat_id=900100,
            message_id=10,
            update_id=1010,
            text=None,
            attachment=CreateAttachmentCommand(
                type=TelegramAttachmentType.VOICE,
                file_id="voice-file",
            ),
        )
    )

    async with ingress_sessionmaker() as session:
        message = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            result.user_message_id
        )

    assert coordinator.chat_ids == [900100]
    assert message is not None
    assert message.attachment is not None
    assert message.attachment.status == AttachmentStatus.FAILED


async def test_terminal_processing_result_invokes_coordinator_after_update(
    ingress_uow_factory,
    ingress_sessionmaker,
    ingress_message_factory,
) -> None:
    message = await ingress_message_factory(
        attachment_type=TelegramAttachmentType.VIDEO_NOTE,
        text=None,
    )
    async with ingress_sessionmaker() as session:
        persisted = await AsyncSqlAlchemyUserMessageRepository(session).get_by_id(
            message.id
        )
        assert persisted is not None
        assert persisted.attachment is not None
        attachment_id = persisted.attachment.id

    coordinator = RecordingCoordinator()
    result = await AsyncAttachmentProcessingResultService(
        uow_factory=ingress_uow_factory,
        conversation_coordinator=coordinator,
    ).apply(
        ApplyAttachmentProcessingResultCommand(
            ingress_message_id=message.id,
            ingress_attachment_id=attachment_id,
            status=AttachmentProcessingResultStatus.FAILED,
        )
    )

    assert result.applied is True
    assert coordinator.chat_ids == [message.chat_id]
