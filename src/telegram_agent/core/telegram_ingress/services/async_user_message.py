from contextlib import AbstractAsyncContextManager
from typing import Callable
from uuid import UUID
from telegram_agent.core.common.exceptions import (
    ContentProcessingBadResponseError,
    ContentProcessingUnavailableError,
)
from telegram_agent.core.telegram_ingress.clients.content_processing import ContentProcessingClient
from telegram_agent.core.telegram_ingress.common.commands import (
    CreateUserMessageCommand,
    ProcessAttachmentCommand,
)
from telegram_agent.core.telegram_ingress.common.results import CreateUserMessageResult
from telegram_agent.core.telegram_ingress.common.types import AttachmentStatus
from telegram_agent.core.telegram_ingress.db.models.user_message import (
    Attachment,
    UserMessage,
)
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)




class AsyncUserMessageService:
    def __init__(
        self,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork],
        ],
        content_processing_client: ContentProcessingClient,
    ) -> None:
        self._uow_factory = uow_factory
        self._content_processing_client = content_processing_client

    async def create_user_message(
        self,
        command: CreateUserMessageCommand,
    ) -> CreateUserMessageResult:
        result = await self._save_user_message(command)

        if result.process_attachment_command is None:
            return result

        if not result.was_created:
            return result

        await self._dispatch_attachment(result)

        return result

    async def _save_user_message(
            self,
            command: CreateUserMessageCommand,
    ) -> CreateUserMessageResult:
        async with self._uow_factory() as uow:
            existing = await uow.user_messages.get_existing(
                update_id=command.update_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
            )

            if existing is not None:
                return CreateUserMessageResult(
                    user_message_id=existing.id,
                    attachment_id=None,
                    process_attachment_command=None,
                    was_created=False,
                )

            user_message = UserMessage(
                telegram_user_id=command.telegram_user_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
                update_id=command.update_id,
                reply_message_id=command.reply_message_id,
                text=command.text,
            )

            attachment: Attachment | None = None

            if command.attachment is not None:
                attachment = Attachment(
                    type=command.attachment.type,
                    file_id=command.attachment.file_id,
                    file_unique_id=command.attachment.file_unique_id,
                )
                user_message.attachment = attachment

            uow.user_messages.add(user_message)
            await uow.flush()

            process_attachment_command: ProcessAttachmentCommand | None = None
            attachment_id: UUID | None = None

            if attachment is not None:
                attachment_id = attachment.id
                process_attachment_command = ProcessAttachmentCommand.create(
                    ingress_message_id=user_message.id,
                    ingress_attachment_id=attachment.id,
                    telegram_user_id=user_message.telegram_user_id,
                    telegram_file_id=attachment.file_id,
                    telegram_file_unique_id=attachment.file_unique_id,
                    attachment_type=attachment.type,
                    callback_required=True,
                )

            return CreateUserMessageResult(
                user_message_id=user_message.id,
                attachment_id=attachment_id,
                process_attachment_command=process_attachment_command,
                was_created=True,
            )

    async def _dispatch_attachment(
        self,
        result: CreateUserMessageResult,
    ) -> None:
        if result.attachment_id is None:
            return

        if result.process_attachment_command is None:
            return

        try:
            await self._content_processing_client.process_attachment(
                result.process_attachment_command,
            )

        except (
            ContentProcessingUnavailableError,
            ContentProcessingBadResponseError,
        ):
            await self._set_attachment_status(
                result.attachment_id,
                AttachmentStatus.FAILED,
            )
            return

        await self._set_attachment_status(
            result.attachment_id,
            AttachmentStatus.PROCESSING,
        )

    async def _set_attachment_status(
        self,
        attachment_id: UUID,
        status: AttachmentStatus,
    ) -> None:
        async with self._uow_factory() as uow:
            await uow.user_messages.update_attachment_status(
                attachment_id=attachment_id,
                status=status,
            )
