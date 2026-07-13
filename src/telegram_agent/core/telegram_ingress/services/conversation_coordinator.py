from contextlib import AbstractAsyncContextManager
from hashlib import sha256
from typing import Callable

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.telegram_ingress.common.commands import (
    RuntimeAttachmentPayload,
    RuntimeMessageBatchPayload,
    RuntimeMessagePayload,
)
from telegram_agent.core.telegram_ingress.common.results import CoordinateConversationResult
from telegram_agent.core.telegram_ingress.common.types import (
    AttachmentStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage
from telegram_agent.core.telegram_ingress.db.uow.async_telegram_ingress import (
    AsyncSqlAlchemyTelegramIngressUnitOfWork,
)

_BLOCKING_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VOICE,
        TelegramAttachmentType.VIDEO_NOTE,
    }
)
_TERMINAL_ATTACHMENT_STATUSES = frozenset(
    {
        AttachmentStatus.READY,
        AttachmentStatus.FAILED,
    }
)


class ConversationCoordinator:
    def __init__(
        self,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyTelegramIngressUnitOfWork],
        ],
    ) -> None:
        self._uow_factory = uow_factory

    async def coordinate(self, chat_id: int) -> CoordinateConversationResult:
        async with self._uow_factory() as uow:
            await uow.user_messages.acquire_chat_lock(chat_id)
            messages = await uow.user_messages.get_pending_for_chat(chat_id)
            if not messages:
                return CoordinateConversationResult(
                    outbox_event_id=None,
                    message_count=0,
                )

            if any(self._has_blocking_attachment(message) for message in messages):
                return CoordinateConversationResult(
                    outbox_event_id=None,
                    message_count=0,
                    blocked=True,
                )

            payload = self._build_payload(chat_id=chat_id, messages=messages)
            idempotency_key = self._idempotency_key(
                chat_id=chat_id,
                messages=messages,
            )
            event = await uow.outbox_events.get_by_idempotency_key(idempotency_key)
            if event is None:
                event = await uow.outbox_events.add(
                    ConversationOutboxEvent(
                        event_type=OutboxEventType.CONVERSATION_MESSAGES_ENQUEUED,
                        chat_id=chat_id,
                        first_message_id=messages[0].message_id,
                        idempotency_key=idempotency_key,
                        payload=payload.model_dump(mode="json"),
                    )
                )

            await uow.user_messages.mark_enqueued(
                messages=messages,
                dispatch_event_id=event.id,
            )
            return CoordinateConversationResult(
                outbox_event_id=event.id,
                message_count=len(messages),
            )

    @staticmethod
    def _has_blocking_attachment(message: UserMessage) -> bool:
        attachment = message.attachment
        return (
            attachment is not None
            and attachment.type in _BLOCKING_ATTACHMENT_TYPES
            and attachment.status not in _TERMINAL_ATTACHMENT_STATUSES
        )

    @staticmethod
    def _build_payload(
        *,
        chat_id: int,
        messages: list[UserMessage],
    ) -> RuntimeMessageBatchPayload:
        payload_messages: list[RuntimeMessagePayload] = []
        for message in messages:
            attachment_payload: RuntimeAttachmentPayload | None = None
            if message.attachment is not None:
                attachment_payload = RuntimeAttachmentPayload(
                    ingress_attachment_id=message.attachment.id,
                    type=message.attachment.type,
                    status=message.attachment.status,
                    file_id=message.attachment.file_id,
                    file_unique_id=message.attachment.file_unique_id,
                )
            payload_messages.append(
                RuntimeMessagePayload(
                    ingress_message_id=message.id,
                    telegram_user_id=message.telegram_user_id,
                    message_id=message.message_id,
                    reply_message_id=message.reply_message_id,
                    text=message.text,
                    attachment=attachment_payload,
                )
            )
        return RuntimeMessageBatchPayload(
            chat_id=chat_id,
            messages=tuple(payload_messages),
        )

    @staticmethod
    def _idempotency_key(
        *,
        chat_id: int,
        messages: list[UserMessage],
    ) -> str:
        message_fingerprint = ",".join(str(message.id) for message in messages)
        digest = sha256(message_fingerprint.encode("ascii")).hexdigest()
        return f"telegram-ingress:conversation:{chat_id}:{digest}:v1"
