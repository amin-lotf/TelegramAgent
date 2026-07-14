from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.agent_runtime.common.commands import (
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.types import ClaimStatus
from telegram_agent.core.agent_runtime.db.models.runtime import ConversationClaim
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.common.utils import utcnow


async def _seed(agent_runtime_uow_factory, chat_id: int, key: str) -> None:
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key=key,
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="a",
                ),
            ),
        )
    )


@pytest.mark.asyncio
async def test_claim_excludes_already_claimed_conversation(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 6001
    await _seed(agent_runtime_uow_factory, chat_id, "claim-1")

    with agent_runtime_sync_uow_factory() as uow:
        first = uow.conversation_claims.claim_available_conversations(
            batch_size=5,
            lease_timeout=timedelta(minutes=5),
            process_owner="owner-1",
        )
    with agent_runtime_sync_uow_factory() as uow:
        second = uow.conversation_claims.claim_available_conversations(
            batch_size=5,
            lease_timeout=timedelta(minutes=5),
            process_owner="owner-2",
        )

    assert len(first) == 1
    assert first[0].chat_id == chat_id
    assert first[0].claim_token is not None
    assert second == []


@pytest.mark.asyncio
async def test_expired_claim_is_recoverable_with_new_token(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 6002
    await _seed(agent_runtime_uow_factory, chat_id, "claim-expire")

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="stale-owner",
        )
        assert len(claimed) == 1
        old_token = claimed[0].claim_token

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        claim.locked_at = utcnow() - timedelta(minutes=10)
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        recovered = uow.conversation_claims.recover_expired_claims(
            lease_timeout=timedelta(minutes=1),
        )
        assert recovered == 1
        reclaimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="fresh-owner",
        )

    assert len(reclaimed) == 1
    assert reclaimed[0].claim_token != old_token


@pytest.mark.asyncio
async def test_fairness_orders_by_oldest_pending_outbox(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    # Create chats in reverse order of desired fairness; oldest outbox should win.
    for chat_id in (6103, 6102, 6101):
        await _seed(agent_runtime_uow_factory, chat_id, f"fair-{chat_id}")

    from sqlalchemy import select

    from telegram_agent.core.agent_runtime.db.models.runtime import OutboxEvent

    with agent_runtime_sync_sessionmaker() as session:
        for chat_id, minutes_ago in ((6101, 30), (6102, 20), (6103, 10)):
            events = list(
                session.scalars(
                    select(OutboxEvent).where(OutboxEvent.chat_id == chat_id)
                ).all()
            )
            for event in events:
                event.created_at = utcnow() - timedelta(minutes=minutes_ago)
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=2,
            lease_timeout=timedelta(minutes=5),
            process_owner="fair-owner",
        )

    assert [c.chat_id for c in claimed] == [6101, 6102]


@pytest.mark.asyncio
async def test_skip_locked_prevents_concurrent_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
        SyncSqlAlchemyAgentRuntimeUnitOfWork,
    )

    chat_id = 6201
    await _seed(agent_runtime_uow_factory, chat_id, "skip-locked")

    session_a = agent_runtime_sync_sessionmaker()
    session_b = agent_runtime_sync_sessionmaker()
    try:
        uow_a = SyncSqlAlchemyAgentRuntimeUnitOfWork(session_a)
        first = uow_a.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="a",
        )
        uow_b = SyncSqlAlchemyAgentRuntimeUnitOfWork(session_b)
        second = uow_b.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="b",
        )

        assert len(first) == 1
        assert second == []
        session_a.commit()
        session_b.commit()
    finally:
        session_a.close()
        session_b.close()

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        assert claim.status == ClaimStatus.CLAIMED
        assert claim.claim_token == first[0].claim_token
