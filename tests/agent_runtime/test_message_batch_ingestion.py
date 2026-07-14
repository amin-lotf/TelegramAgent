from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from telegram_agent.core.agent_runtime.common.commands import (
    IngestAttachmentCommand,
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    OutboxEventStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
    RuntimeBatch,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.common.exceptions import AgentRuntimeBatchConflictError
from telegram_agent.core.common.types import TelegramAttachmentType

pytestmark = pytest.mark.asyncio


def _text_message(*, ingress_id=None, message_id=10, text="hello") -> IngestMessageCommand:
    return IngestMessageCommand(
        ingress_message_id=ingress_id or uuid4(),
        telegram_user_id=1,
        message_id=message_id,
        text=text,
    )


async def test_ingests_batch_messages_outbox_and_claim(
    agent_runtime_uow_factory,
    agent_runtime_sessionmaker,
) -> None:
    batch_id = uuid4()
    ingress_a = uuid4()
    ingress_b = uuid4()
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)

    result = await service.ingest(
        IngestMessageBatchCommand(
            batch_id=batch_id,
            chat_id=101,
            idempotency_key="batch-key-1",
            messages=(
                _text_message(ingress_id=ingress_a, message_id=10, text="hello"),
                IngestMessageCommand(
                    ingress_message_id=ingress_b,
                    telegram_user_id=1,
                    message_id=20,
                    text=None,
                    attachment=IngestAttachmentCommand(
                        ingress_attachment_id=uuid4(),
                        type=TelegramAttachmentType.VIDEO,
                        status="ready",
                        file_id="file-1",
                        file_unique_id="unique-1",
                    ),
                ),
            ),
        )
    )

    assert result.created is True
    assert result.message_count == 2

    async with agent_runtime_sessionmaker() as session:
        batch = await session.get(RuntimeBatch, batch_id)
        messages = list(
            (
                await session.scalars(
                    select(RuntimeMessage).where(RuntimeMessage.batch_id == batch_id)
                )
            ).all()
        )
        events = list((await session.scalars(select(OutboxEvent))).all())
        claim = await session.get(ConversationClaim, 101)

    assert batch is not None
    assert len(messages) == 2
    assert {m.coordination_status for m in messages} == {CoordinationStatus.PENDING}
    assert len(events) == 2
    assert all(event.status == OutboxEventStatus.PENDING for event in events)
    assert claim is not None
    assert claim.status.value == "idle"
    assert claim.claim_token is None


async def test_idempotent_batch_retry(
    agent_runtime_uow_factory,
) -> None:
    batch_id = uuid4()
    ingress_id = uuid4()
    command = IngestMessageBatchCommand(
        batch_id=batch_id,
        chat_id=202,
        idempotency_key="same-key",
        messages=(_text_message(ingress_id=ingress_id, message_id=1, text="once"),),
    )
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)

    first = await service.ingest(command)
    second = await service.ingest(command)

    assert first.created is True
    assert second.created is False
    assert second.batch_id == first.batch_id
    assert second.message_count == 1


async def test_conflicting_idempotency_key_raises(
    agent_runtime_uow_factory,
) -> None:
    batch_id = uuid4()
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)
    await service.ingest(
        IngestMessageBatchCommand(
            batch_id=batch_id,
            chat_id=303,
            idempotency_key="key-a",
            messages=(_text_message(message_id=1, text="a"),),
        )
    )

    with pytest.raises(AgentRuntimeBatchConflictError):
        await service.ingest(
            IngestMessageBatchCommand(
                batch_id=batch_id,
                chat_id=303,
                idempotency_key="key-b",
                messages=(_text_message(message_id=2, text="b"),),
            )
        )


async def test_conflicting_ingress_message_from_other_batch_raises(
    agent_runtime_uow_factory,
    agent_runtime_sessionmaker,
) -> None:
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)
    shared_ingress = uuid4()
    await service.ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=404,
            idempotency_key="batch-a",
            messages=(_text_message(ingress_id=shared_ingress, message_id=1, text="a"),),
        )
    )

    with pytest.raises(AgentRuntimeBatchConflictError):
        await service.ingest(
            IngestMessageBatchCommand(
                batch_id=uuid4(),
                chat_id=404,
                idempotency_key="batch-b",
                messages=(
                    _text_message(ingress_id=shared_ingress, message_id=2, text="b"),
                    _text_message(message_id=3, text="c"),
                ),
            )
        )

    async with agent_runtime_sessionmaker() as session:
        batches = list(await session.scalars(select(RuntimeBatch)))
        messages = list(await session.scalars(select(RuntimeMessage)))

    assert len(batches) == 1
    assert len(messages) == 1


async def test_conflicting_content_same_ingress_raises(
    agent_runtime_uow_factory,
) -> None:
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)
    ingress_id = uuid4()
    await service.ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=505,
            idempotency_key="orig",
            messages=(_text_message(ingress_id=ingress_id, message_id=1, text="original"),),
        )
    )

    with pytest.raises(AgentRuntimeBatchConflictError):
        await service.ingest(
            IngestMessageBatchCommand(
                batch_id=uuid4(),
                chat_id=505,
                idempotency_key="changed",
                messages=(_text_message(ingress_id=ingress_id, message_id=1, text="changed"),),
            )
        )


async def test_attachment_status_difference_is_not_identity_conflict(
    agent_runtime_uow_factory,
    agent_runtime_sessionmaker,
) -> None:
    """Status is mutable; same immutable attachment identity must not conflict."""
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)
    batch_id = uuid4()
    ingress_id = uuid4()
    attachment_id = uuid4()
    base_attachment = dict(
        ingress_attachment_id=attachment_id,
        type=TelegramAttachmentType.VOICE,
        file_id="voice-file",
        file_unique_id="voice-unique",
    )

    first = await service.ingest(
        IngestMessageBatchCommand(
            batch_id=batch_id,
            chat_id=606,
            idempotency_key="status-key",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=ingress_id,
                    telegram_user_id=1,
                    message_id=1,
                    text=None,
                    attachment=IngestAttachmentCommand(
                        status="processing",
                        **base_attachment,
                    ),
                ),
            ),
        )
    )
    second = await service.ingest(
        IngestMessageBatchCommand(
            batch_id=batch_id,
            chat_id=606,
            idempotency_key="status-key",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=ingress_id,
                    telegram_user_id=1,
                    message_id=1,
                    text=None,
                    attachment=IngestAttachmentCommand(
                        status="ready",
                        **base_attachment,
                    ),
                ),
            ),
        )
    )

    assert first.created is True
    assert second.created is False

    async with agent_runtime_sessionmaker() as session:
        messages = list(await session.scalars(select(RuntimeMessage)))
        events = list(await session.scalars(select(OutboxEvent)))

    assert len(messages) == 1
    assert len(events) == 1
    # Ingest does not rewrite status; a future updater owns that mutation.
    assert messages[0].attachment_status == "processing"


async def test_immutable_field_conflict_rolls_back_partial_batch(
    agent_runtime_uow_factory,
    agent_runtime_sessionmaker,
) -> None:
    service = AsyncMessageBatchIngestionService(agent_runtime_uow_factory)
    shared_ingress = uuid4()
    await service.ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=707,
            idempotency_key="owner",
            messages=(_text_message(ingress_id=shared_ingress, message_id=1, text="owned"),),
        )
    )

    with pytest.raises(AgentRuntimeBatchConflictError):
        await service.ingest(
            IngestMessageBatchCommand(
                batch_id=uuid4(),
                chat_id=707,
                idempotency_key="partial-fail",
                messages=(
                    _text_message(message_id=10, text="new first"),
                    _text_message(ingress_id=shared_ingress, message_id=11, text="conflict"),
                    _text_message(message_id=12, text="would be third"),
                ),
            )
        )

    async with agent_runtime_sessionmaker() as session:
        batches = list(await session.scalars(select(RuntimeBatch)))
        messages = list(await session.scalars(select(RuntimeMessage)))

    assert len(batches) == 1
    assert len(messages) == 1
    assert messages[0].text == "owned"
