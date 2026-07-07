from contextlib import AbstractAsyncContextManager
from typing import Callable

from telegram_agent.core.telegram_ingress.common.commands import CreateUserMessageCommand
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage, Attachment
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import AsyncSqlAlchemyTelegramIngressUnitOfWork


class AsyncUserMessageService:
    def __init__(self,
                 uow_factory: Callable[
                     [],
                     AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork]
                 ]
                 ) -> None:
        self._uow_factory = uow_factory

    async def create_user_message(self, command: CreateUserMessageCommand) -> UserMessage:
        async with self._uow_factory() as uow:
            existing = await uow.user_messages.get_existing(
                update_id=command.update_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
            )
            if existing is not None:
                return existing
            user_message = UserMessage(
                telegram_user_id=command.telegram_user_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
                update_id=command.update_id,
                reply_message_id=command.reply_message_id,
                text=command.text,
            )
            if command.attachment is not None:
                user_message.attachment = Attachment(
                    type=command.attachment.type,
                    file_id=command.attachment.file_id,
                    file_unique_id=command.attachment.file_unique_id,
                )
            uow.user_messages.add(user_message)
            await uow.flush()
            return user_message
