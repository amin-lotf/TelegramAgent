from __future__ import annotations

from uuid import uuid4

import pytest

from telegram_agent.core.telegram_ingress.services.async_user_notification import (
    AsyncUserNotificationService,
)


class _Bot:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def send_message(self, **kwargs) -> int:
        self.calls.append(kwargs)
        return 999


class _UserMessages:
    def __init__(self, message) -> None:
        self._message = message

    async def get_by_id(self, message_id):
        if self._message is not None and self._message.id == message_id:
            return self._message
        return None


class _Uow:
    def __init__(self, message) -> None:
        self.user_messages = _UserMessages(message)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class _Message:
    def __init__(self, *, message_id: int, chat_id: int) -> None:
        self.id = uuid4()
        self.message_id = message_id
        self.chat_id = chat_id


@pytest.mark.asyncio
async def test_notify_uses_explicit_reply_to_without_db_lookup() -> None:
    bot = _Bot()
    service = AsyncUserNotificationService(
        uow_factory=lambda: _Uow(None),  # type: ignore[arg-type,return-value]
        telegram_bot_client=bot,  # type: ignore[arg-type]
    )
    sent_id = await service.notify(
        chat_id=1,
        telegram_user_id=2,
        text="Preparing…",
        reply_to_message_id=55,
    )
    assert sent_id == 999
    assert bot.calls == [
        {"chat_id": 1, "text": "Preparing…", "reply_to_message_id": 55}
    ]


@pytest.mark.asyncio
async def test_notify_resolves_reply_from_ingress_message() -> None:
    message = _Message(message_id=88, chat_id=10)
    bot = _Bot()
    service = AsyncUserNotificationService(
        uow_factory=lambda: _Uow(message),  # type: ignore[arg-type,return-value]
        telegram_bot_client=bot,  # type: ignore[arg-type]
    )
    await service.notify(
        chat_id=10,
        telegram_user_id=2,
        text="Sorry, not a download request.",
        ingress_message_id=message.id,
    )
    assert bot.calls[0]["reply_to_message_id"] == 88
