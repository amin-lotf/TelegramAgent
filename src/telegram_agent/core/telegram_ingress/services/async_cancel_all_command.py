from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Callable

from telegram_agent.core.telegram_ingress.common.commands import (
    CancelAllSecondaryTasksPayload,
    CreateUserMessageCommand,
)
from telegram_agent.core.telegram_ingress.common.types import (
    ConversationStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)


class AsyncCancelAllCommandService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [], AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork]
        ],
    ) -> None:
        self._uow_factory = uow_factory

    async def accept(self, command: CreateUserMessageCommand) -> None:
        async with self._uow_factory() as uow:
            existing = await uow.user_messages.get_existing(
                update_id=command.update_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
            )
            if existing is not None:
                return
            message = UserMessage(
                telegram_user_id=command.telegram_user_id,
                chat_id=command.chat_id,
                message_id=command.message_id,
                update_id=command.update_id,
                reply_message_id=command.reply_message_id,
                text=command.text,
            )
            uow.user_messages.add(message)
            await uow.flush()
            idempotency_key = (
                f"telegram-ingress:cancel-all:update:{command.update_id}:v1"
                if command.update_id is not None
                else (
                    "telegram-ingress:cancel-all:"
                    f"chat:{command.chat_id}:message:{command.message_id}:v1"
                )
            )
            event = await uow.outbox_events.add(
                ConversationOutboxEvent(
                    event_type=OutboxEventType.CANCEL_ALL_SECONDARY_TASKS_REQUESTED,
                    chat_id=command.chat_id,
                    first_message_id=command.message_id,
                    idempotency_key=idempotency_key,
                    payload=CancelAllSecondaryTasksPayload(
                        telegram_user_id=command.telegram_user_id,
                        chat_id=command.chat_id,
                        command_message_id=command.message_id,
                    ).model_dump(mode="json"),
                )
            )
            message.conversation_status = ConversationStatus.ENQUEUED
            message.dispatch_event_id = event.id
