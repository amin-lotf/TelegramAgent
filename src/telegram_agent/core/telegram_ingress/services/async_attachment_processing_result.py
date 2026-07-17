from contextlib import AbstractAsyncContextManager
from typing import Callable
import logging
from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.telegram_ingress.common.commands import (
    ApplyAttachmentProcessingResultCommand,
)
from telegram_agent.core.telegram_ingress.common.results import (
    ApplyAttachmentProcessingResultResult,
)
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)
from telegram_agent.core.telegram_ingress.services.conversation_coordinator import (
    ConversationCoordinator,
)

logger = logging.getLogger(__name__)

_MESSAGE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VOICE,
        TelegramAttachmentType.VIDEO_NOTE,
    }
)


class AsyncAttachmentProcessingResultService:
    def __init__(
        self,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork],
        ],
        conversation_coordinator: ConversationCoordinator,
    ) -> None:
        self._uow_factory = uow_factory
        self._conversation_coordinator = conversation_coordinator

    async def apply(self, command: ApplyAttachmentProcessingResultCommand) -> ApplyAttachmentProcessingResultResult:
        chat_id: int | None = None
        async with self._uow_factory() as uow:
            message = await uow.user_messages.get_by_id(command.ingress_message_id)
            if message is None or message.attachment is None:
                return ApplyAttachmentProcessingResultResult(applied=False)
            if message.attachment.id != command.ingress_attachment_id:
                return ApplyAttachmentProcessingResultResult(applied=False)

            chat_id = message.chat_id
            # TIMED_OUT is accepted from content-processing and stored as FAILED for
            # now; a later ingress expectation phase may preserve timed_out distinctly.
            if command.status == AttachmentProcessingResultStatus.COMPLETED:
                message.attachment.status = AttachmentStatus.READY
            else:
                message.attachment.status = AttachmentStatus.FAILED
            if (
                command.status == AttachmentProcessingResultStatus.COMPLETED
                and command.transcribed_text is not None
                and message.attachment.type in _MESSAGE_ATTACHMENT_TYPES
            ):
                message.text = command.transcribed_text

            await uow.flush()

        if chat_id is not None:
            await self._conversation_coordinator.coordinate(chat_id)
        return ApplyAttachmentProcessingResultResult(applied=True)
