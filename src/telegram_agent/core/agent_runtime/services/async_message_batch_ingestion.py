from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from telegram_agent.core.agent_runtime.common.commands import (
    IngestAttachmentCommand,
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.results import IngestMessageBatchResult
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    OutboxEventType,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    OutboxEvent,
    RuntimeBatch,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.db.uow.async_agent_runtime import (
    AsyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.common.exceptions import AgentRuntimeBatchConflictError


class AsyncMessageBatchIngestionService:
    """Persist ordered runtime batches transactionally.

    Immutable message/attachment identifiers define ownership and conflict
    detection. ``attachment_status`` is intentionally *not* part of permanent
    identity so a future explicit status-update path can mutate it without
    changing batch ownership or coordination idempotency keys.
    """

    def __init__(
        self,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyAgentRuntimeUnitOfWork],
        ],
    ) -> None:
        self._uow_factory = uow_factory

    async def ingest(
        self,
        command: IngestMessageBatchCommand,
    ) -> IngestMessageBatchResult:
        try:
            return await self._ingest_once(command)
        except IntegrityError as exc:
            recovered = await self._recover_idempotent(command)
            if recovered is not None:
                return recovered
            raise AgentRuntimeBatchConflictError(
                "Failed to persist runtime message batch due to a conflict"
            ) from exc

    async def _ingest_once(
        self,
        command: IngestMessageBatchCommand,
    ) -> IngestMessageBatchResult:
        async with self._uow_factory() as uow:
            existing_by_id = await uow.batches.get_by_id(command.batch_id)
            if existing_by_id is not None:
                return await self._accept_existing_batch(
                    uow=uow,
                    batch=existing_by_id,
                    command=command,
                )

            existing_by_key = await uow.batches.get_by_idempotency_key(
                command.idempotency_key
            )
            if existing_by_key is not None:
                if existing_by_key.id != command.batch_id:
                    raise AgentRuntimeBatchConflictError(
                        "idempotency key already used by a different batch"
                    )
                return await self._accept_existing_batch(
                    uow=uow,
                    batch=existing_by_key,
                    command=command,
                )

            batch = RuntimeBatch(
                id=command.batch_id,
                chat_id=command.chat_id,
                idempotency_key=command.idempotency_key,
            )
            uow.batches.add(batch)
            await uow.conversation_claims.ensure_idle(command.chat_id)

            for message_command in command.messages:
                existing_message = await uow.messages.get_by_ingress_message_id(
                    message_command.ingress_message_id
                )
                if existing_message is not None:
                    if not self._immutable_identity_matches(
                        existing_message,
                        message_command,
                        batch_id=command.batch_id,
                        chat_id=command.chat_id,
                    ):
                        raise AgentRuntimeBatchConflictError(
                            "ingress_message_id already exists with different content "
                            "or belongs to another batch"
                        )
                    # Same immutable identity: accept without rewriting mutable
                    # attachment_status or creating duplicate outbox work.
                    continue

                message = self._build_message(
                    batch_id=command.batch_id,
                    chat_id=command.chat_id,
                    message_command=message_command,
                )
                uow.messages.add(message)
                await uow.flush()
                await self._ensure_outbox_event(uow, message)

            await uow.flush()
            all_messages = await uow.messages.list_by_batch_id(command.batch_id)
            return IngestMessageBatchResult(
                batch_id=command.batch_id,
                chat_id=command.chat_id,
                created=True,
                message_count=len(all_messages),
            )

    async def _accept_existing_batch(
        self,
        *,
        uow: AsyncSqlAlchemyAgentRuntimeUnitOfWork,
        batch: RuntimeBatch,
        command: IngestMessageBatchCommand,
    ) -> IngestMessageBatchResult:
        if batch.idempotency_key != command.idempotency_key:
            raise AgentRuntimeBatchConflictError(
                "batch_id already exists with a different idempotency key"
            )
        if batch.chat_id != command.chat_id:
            raise AgentRuntimeBatchConflictError(
                "batch already exists for a different chat_id"
            )

        stored = await uow.messages.list_by_batch_id(batch.id)
        self._assert_batch_messages_match(stored, command)
        return IngestMessageBatchResult(
            batch_id=batch.id,
            chat_id=batch.chat_id,
            created=False,
            message_count=len(stored),
        )

    def _assert_batch_messages_match(
        self,
        stored: list[RuntimeMessage],
        command: IngestMessageBatchCommand,
    ) -> None:
        if len(stored) != len(command.messages):
            raise AgentRuntimeBatchConflictError(
                "existing batch message count does not match the request"
            )
        by_ingress = {message.ingress_message_id: message for message in stored}
        for message_command in command.messages:
            existing = by_ingress.get(message_command.ingress_message_id)
            if existing is None:
                raise AgentRuntimeBatchConflictError(
                    "existing batch is missing a requested ingress_message_id"
                )
            if not self._immutable_identity_matches(
                existing,
                message_command,
                batch_id=command.batch_id,
                chat_id=command.chat_id,
            ):
                raise AgentRuntimeBatchConflictError(
                    "existing batch message contents do not match the request"
                )

    @staticmethod
    def _immutable_identity_matches(
        stored: RuntimeMessage,
        command: IngestMessageCommand,
        *,
        batch_id: UUID,
        chat_id: int,
    ) -> bool:
        """Compare ownership and content identity; ignore attachment_status."""
        if stored.batch_id != batch_id:
            return False
        if stored.chat_id != chat_id:
            return False
        if stored.ingress_message_id != command.ingress_message_id:
            return False
        if stored.telegram_user_id != command.telegram_user_id:
            return False
        if stored.message_id != command.message_id:
            return False
        if stored.reply_message_id != command.reply_message_id:
            return False
        if stored.text != command.text:
            return False
        return AsyncMessageBatchIngestionService._attachment_identity_matches(
            stored,
            command.attachment,
        )

    @staticmethod
    def _attachment_identity_matches(
        stored: RuntimeMessage,
        attachment: IngestAttachmentCommand | None,
    ) -> bool:
        if attachment is None:
            return (
                stored.attachment_ingress_id is None
                and stored.attachment_type is None
                and stored.attachment_file_id is None
                and stored.attachment_file_unique_id is None
            )
        return (
            stored.attachment_ingress_id == attachment.ingress_attachment_id
            and stored.attachment_type == attachment.type
            and stored.attachment_file_id == attachment.file_id
            and stored.attachment_file_unique_id == attachment.file_unique_id
        )

    @staticmethod
    def _build_message(
        *,
        batch_id: UUID,
        chat_id: int,
        message_command: IngestMessageCommand,
    ) -> RuntimeMessage:
        message = RuntimeMessage(
            batch_id=batch_id,
            ingress_message_id=message_command.ingress_message_id,
            chat_id=chat_id,
            telegram_user_id=message_command.telegram_user_id,
            message_id=message_command.message_id,
            reply_message_id=message_command.reply_message_id,
            text=message_command.text,
            coordination_status=CoordinationStatus.PENDING,
        )
        if message_command.attachment is not None:
            message.attachment_ingress_id = (
                message_command.attachment.ingress_attachment_id
            )
            message.attachment_type = message_command.attachment.type
            message.attachment_status = message_command.attachment.status
            message.attachment_file_id = message_command.attachment.file_id
            message.attachment_file_unique_id = (
                message_command.attachment.file_unique_id
            )
        return message

    @staticmethod
    async def _ensure_outbox_event(
        uow: AsyncSqlAlchemyAgentRuntimeUnitOfWork,
        message: RuntimeMessage,
    ) -> None:
        event_type = OutboxEventType.MESSAGE_PENDING_COORDINATION
        idempotency_key = f"agent_runtime:coordinate:{message.ingress_message_id}:v1"
        existing_event = await uow.outbox_events.get_by_idempotency_key(idempotency_key)
        if existing_event is not None:
            return
        uow.outbox_events.add(
            OutboxEvent(
                event_type=event_type.value,
                chat_id=message.chat_id,
                runtime_message_id=message.id,
                message_id=message.message_id,
                idempotency_key=idempotency_key,
                payload={
                    "ingress_message_id": str(message.ingress_message_id),
                    "chat_id": message.chat_id,
                    "message_id": message.message_id,
                },
            )
        )

    async def _recover_idempotent(
        self,
        command: IngestMessageBatchCommand,
    ) -> IngestMessageBatchResult | None:
        async with self._uow_factory() as uow:
            existing_by_id = await uow.batches.get_by_id(command.batch_id)
            if existing_by_id is None:
                existing_by_key = await uow.batches.get_by_idempotency_key(
                    command.idempotency_key
                )
                if existing_by_key is None or existing_by_key.id != command.batch_id:
                    return None
                existing_by_id = existing_by_key
            try:
                return await self._accept_existing_batch(
                    uow=uow,
                    batch=existing_by_id,
                    command=command,
                )
            except AgentRuntimeBatchConflictError:
                return None
