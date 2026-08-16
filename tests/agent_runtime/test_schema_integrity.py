from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.agent_runtime.common.commands import (
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.types import (
    AgentMessageRole,
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    AgentMessage,
    ConversationClaim,
    ConversationGroup,
    OutboxEvent,
    RuntimeBatch,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.common.utils import utcnow
from sqlalchemy import select


@pytest.mark.asyncio
async def test_cross_chat_group_reference_is_rejected_by_fk(
    agent_runtime_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=8001,
            idempotency_key="fk-owner",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="owner chat",
                ),
            ),
        )
    )

    with agent_runtime_sync_sessionmaker() as session:
        foreign_group = ConversationGroup(
            id=uuid4(),
            chat_id=8002,
            group_number=1,
        )
        session.add(foreign_group)
        session.flush()

        message = session.query(RuntimeMessage).one()
        message.group_id = foreign_group.id
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_claim_check_rejects_idle_with_token(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    with agent_runtime_sync_sessionmaker() as session:
        session.add(
            ConversationClaim(
                chat_id=8101,
                status="idle",
                claim_token=uuid4(),
                locked_at=None,
                locked_by=None,
                available_at=utcnow(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_claim_check_rejects_claimed_without_token(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    with agent_runtime_sync_sessionmaker() as session:
        session.add(
            ConversationClaim(
                chat_id=8102,
                status="claimed",
                claim_token=None,
                locked_at=utcnow(),
                locked_by="worker",
                available_at=utcnow(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_claim_check_rejects_claimed_without_locked_at(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    with agent_runtime_sync_sessionmaker() as session:
        session.add(
            ConversationClaim(
                chat_id=8103,
                status="claimed",
                claim_token=uuid4(),
                locked_at=None,
                locked_by="worker",
                available_at=utcnow(),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_group_numbers_unique_per_chat(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    with agent_runtime_sync_sessionmaker() as session:
        session.add(
            ConversationGroup(id=uuid4(), chat_id=8201, group_number=1)
        )
        session.add(
            ConversationGroup(id=uuid4(), chat_id=8201, group_number=1)
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_same_group_number_allowed_across_chats(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    with agent_runtime_sync_sessionmaker() as session:
        session.add(ConversationGroup(id=uuid4(), chat_id=8301, group_number=1))
        session.add(ConversationGroup(id=uuid4(), chat_id=8302, group_number=1))
        session.commit()


def test_agent_messages_are_unique_per_request_and_role(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    group_id = uuid4()
    first_ingress_id = uuid4()
    with agent_runtime_sync_sessionmaker() as session:
        session.add(ConversationGroup(id=group_id, chat_id=8351, group_number=1))
        session.flush()
        session.add_all(
            [
                AgentMessage(
                    ingress_message_id=first_ingress_id,
                    chat_id=8351,
                    telegram_user_id=1,
                    group_id=group_id,
                    text="first",
                    role=AgentMessageRole.DOWNLOAD_AGENT,
                ),
                AgentMessage(
                    ingress_message_id=uuid4(),
                    chat_id=8351,
                    telegram_user_id=1,
                    group_id=group_id,
                    text="second",
                    role=AgentMessageRole.DOWNLOAD_AGENT,
                ),
            ]
        )
        session.commit()

        session.add(
            AgentMessage(
                ingress_message_id=first_ingress_id,
                chat_id=8351,
                telegram_user_id=1,
                group_id=group_id,
                text="duplicate",
                role=AgentMessageRole.DOWNLOAD_AGENT,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_composite_group_fk_allows_same_chat_assignment(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    batch_id = uuid4()
    group_id = uuid4()
    with agent_runtime_sync_sessionmaker() as session:
        session.add(
            RuntimeBatch(
                id=batch_id,
                chat_id=8401,
                idempotency_key="fk-ok",
            )
        )
        session.add(
            ConversationGroup(id=group_id, chat_id=8401, group_number=1)
        )
        session.add(
            RuntimeMessage(
                batch_id=batch_id,
                ingress_message_id=uuid4(),
                chat_id=8401,
                telegram_user_id=1,
                message_id=1,
                text="ok",
                group_id=group_id,
            )
        )
        session.commit()


def test_no_redundant_unique_group_number_index(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    """Unique constraint covers (chat_id, group_number); extra non-unique index removed."""
    with agent_runtime_sync_sessionmaker() as session:
        rows = session.execute(
            text(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE tablename = 'conversation_groups'
                """
            )
        ).fetchall()
    index_names = {row[0] for row in rows}
    assert "ix_conversation_groups_chat_number" not in index_names
    assert any("uq_conversation_groups_chat_id_group_number" in name for name in index_names)


@pytest.mark.asyncio
async def test_outbox_allows_multiple_event_types_per_message(
    agent_runtime_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=8501,
            idempotency_key="multi-outbox",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="multi",
                ),
            ),
        )
    )

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.INTENT_CLASSIFIER.value,
                chat_id=message.chat_id,
                runtime_message_id=message.id,
                message_id=message.message_id,
                idempotency_key=f"agent_runtime:intent_classifier:{message.ingress_message_id}:v1",
                payload={},
                status=OutboxEventStatus.PENDING,
            )
        )
        session.commit()

        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.runtime_message_id == message.id)
            ).all()
        )
        assert len(events) == 2
        types = {event.event_type for event in events}
        assert types == {
            OutboxEventType.MESSAGE_PENDING_COORDINATION.value,
            OutboxEventType.INTENT_CLASSIFIER.value,
        }

        session.add(
            OutboxEvent(
                event_type=OutboxEventType.INTENT_CLASSIFIER.value,
                chat_id=message.chat_id,
                runtime_message_id=message.id,
                message_id=message.message_id,
                idempotency_key="duplicate-intent",
                payload={},
                status=OutboxEventStatus.PENDING,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
