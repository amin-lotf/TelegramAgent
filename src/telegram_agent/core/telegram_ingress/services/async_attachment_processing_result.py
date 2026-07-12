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
    ) -> None:
        self._uow_factory = uow_factory

    async def apply(self, command: ApplyAttachmentProcessingResultCommand) -> ApplyAttachmentProcessingResultResult:
        async with self._uow_factory() as uow:
            message = await uow.user_messages.get_by_id(command.ingress_message_id)
            if message is None or message.attachment is None:
                return ApplyAttachmentProcessingResultResult(applied=False)
            if message.attachment.id != command.ingress_attachment_id:
                return ApplyAttachmentProcessingResultResult(applied=False)

            message.attachment.status = (
                AttachmentStatus.READY
                if command.status == AttachmentProcessingResultStatus.COMPLETED
                else AttachmentStatus.FAILED
            )
            if (
                command.status == AttachmentProcessingResultStatus.COMPLETED
                and command.transcribed_text is not None
                and message.attachment.type in _MESSAGE_ATTACHMENT_TYPES
            ):
                message.text = command.transcribed_text

            await uow.flush()
            return ApplyAttachmentProcessingResultResult(applied=True)
