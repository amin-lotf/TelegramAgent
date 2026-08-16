"""Send progressive user notifications as Telegram replies."""

from __future__ import annotations

import logging
from contextlib import AbstractAsyncContextManager
from typing import Callable
from uuid import UUID

from telegram_agent.core.common.exceptions import (
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.telegram_ingress.clients.telegram_bot import TelegramBotClient
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)

logger = logging.getLogger(__name__)


class AsyncUserNotificationService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork],
        ],
        telegram_bot_client: TelegramBotClient,
    ) -> None:
        self._uow_factory = uow_factory
        self._telegram_bot_client = telegram_bot_client

    async def notify(
        self,
        *,
        chat_id: int,
        telegram_user_id: int,
        text: str,
        ingress_message_id: UUID | None = None,
        reply_to_message_id: int | None = None,
        group_id: UUID | None = None,
    ) -> int:
        """Resolve reply target if needed and send a Telegram text message.

        Returns the Telegram message_id of the sent notification.
        """
        del telegram_user_id, group_id  # reserved for auth/audit; not needed for send

        resolved_reply_to = reply_to_message_id
        if resolved_reply_to is None and ingress_message_id is not None:
            async with self._uow_factory() as uow:
                message = await uow.user_messages.get_by_id(ingress_message_id)
                if message is not None and message.chat_id == chat_id:
                    resolved_reply_to = message.message_id
                else:
                    logger.warning(
                        "Could not resolve reply target for user notification",
                        extra={
                            "chat_id": chat_id,
                            "ingress_message_id": str(ingress_message_id),
                        },
                    )

        try:
            return self._telegram_bot_client.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=resolved_reply_to,
            )
        except (TelegramDownloadError, TelegramDownloadPermanentError):
            raise
