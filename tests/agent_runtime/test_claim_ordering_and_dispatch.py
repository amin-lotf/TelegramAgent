from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.agent_runtime.common.commands import (
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.settings import Settings
from telegram_agent.core.agent_runtime.common.types import (
    ClaimStatus,
    CoordinationStatus,
    CoordinatorDecisionKind,
    OutboxEventStatus,
)
from telegram_agent.core.agent_runtime.coordinators.base import CoordinatorDecision
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.agent_runtime.services.coordination_outbox_dispatcher import (
    CoordinationOutboxDispatcher,
)
from telegram_agent.core.agent_runtime.services.sync_message_group_coordination import (
    SyncMessageGroupCoordinationService,
)
from telegram_agent.core.common.exceptions import PermanentAgentRuntimeCoordinationError
from telegram_agent.core.common.utils import utcnow


def _settings(**overrides) -> Settings:
    values = {
        "sqlalchemy_database_url": "postgresql://unused",
        "coordination_message_batch_size": 10,
        "coordination_recent_window_size": 10,
        "coordination_claim_lease_seconds": 300,
        "outbox_dispatch_lease_seconds": 60,
        "outbox_retry_base_seconds": 5,
        "outbox_retry_max_seconds": 40,
    }
    values.update(overrides)
    return Settings(**values)


async def _ingest(
    agent_runtime_uow_factory,
    *,
    chat_id: int,
    key: str,
    message_ids: list[int],
) -> None:
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key=key,
            messages=tuple(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=mid,
                    text=f"m{mid}",
                )
                for mid in message_ids
            ),
        )
    )


class AlwaysNew:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)


class PermanentCoordinator:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        raise PermanentAgentRuntimeCoordinationError("hard fail")


class _FakeTask:
    def __init__(self) -> None:
        self.fail = False
        self.calls: list[tuple] = []

    def apply_async(self, *, args, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.calls.append(args)


@pytest.mark.asyncio
async def test_permanent_failure_is_atomic_vague_and_failed(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9101
    await _ingest(
        agent_runtime_uow_factory,
        chat_id=chat_id,
        key="perm-atomic",
        message_ids=[1],
    )
    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="w",
        )
        token = claimed[0].claim_token

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        coordinator=PermanentCoordinator(),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=token)

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        event = session.scalars(select(OutboxEvent)).one()

    assert message.coordination_status == CoordinationStatus.VAGUE
    assert event.status == OutboxEventStatus.FAILED


@pytest.mark.asyncio
async def test_permanent_failure_rolls_back_if_outbox_update_fails(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
    monkeypatch,
) -> None:
    chat_id = 9102
    await _ingest(
        agent_runtime_uow_factory,
        chat_id=chat_id,
        key="perm-rollback",
        message_ids=[1],
    )
    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="w",
        )
        token = claimed[0].claim_token

    from telegram_agent.core.agent_runtime.db.repositories import sync_outbox as outbox_mod

    def fail_mark_failed(*args, **kwargs):
        return None

    monkeypatch.setattr(
        outbox_mod.SyncSqlAlchemyOutboxRepository,
        "mark_failed_for_message",
        fail_mark_failed,
    )

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        coordinator=PermanentCoordinator(),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=token)

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        event = session.scalars(select(OutboxEvent)).one()

    # Neither side committed: no FAILED outbox with pending message, and no vague-only.
    assert message.coordination_status == CoordinationStatus.PENDING
    assert event.status == OutboxEventStatus.PENDING


@pytest.mark.asyncio
async def test_broker_enqueue_failure_schedules_head_outbox_retry_and_releases_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9103
    await _ingest(
        agent_runtime_uow_factory,
        chat_id=chat_id,
        key="broker-fail",
        message_ids=[1, 2],
    )

    task = _FakeTask()
    task.fail = True
    before = utcnow()
    result = CoordinationOutboxDispatcher(
        uow_factory=agent_runtime_sync_uow_factory,
        coordinate_task=task,  # type: ignore[arg-type]
        batch_size=10,
        claim_lease_timeout=timedelta(minutes=5),
        outbox_lease_timeout=timedelta(minutes=1),
        retry_base_delay=timedelta(seconds=5),
        retry_max_delay=timedelta(minutes=5),
        process_owner="dispatcher",
    ).dispatch_once()

    assert result.claimed == 1
    assert result.published == 0
    assert result.retryable_failures == 1

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        events = list(
            session.scalars(
                select(OutboxEvent).order_by(OutboxEvent.message_id)
            ).all()
        )

    assert claim is not None
    assert claim.status == ClaimStatus.IDLE
    assert claim.claim_token is None
    assert claim.available_at > before
    # Head outbox got retry backoff; second event left as-is (still pending).
    assert events[0].status == OutboxEventStatus.PENDING
    assert events[0].attempt_count == 1
    assert events[0].available_at > before
    assert events[1].attempt_count == 0


@pytest.mark.asyncio
async def test_conversation_not_claimed_while_earliest_message_in_retry_backoff(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9104
    await _ingest(
        agent_runtime_uow_factory,
        chat_id=chat_id,
        key="head-backoff",
        message_ids=[1, 2],
    )

    with agent_runtime_sync_sessionmaker() as session:
        events = list(
            session.scalars(
                select(OutboxEvent).order_by(OutboxEvent.message_id)
            ).all()
        )
        events[0].available_at = utcnow() + timedelta(minutes=10)
        events[1].available_at = utcnow() - timedelta(seconds=1)
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=10,
            lease_timeout=timedelta(minutes=5),
            process_owner="w",
        )

    assert claimed == []


@pytest.mark.asyncio
async def test_bounded_batch_leaves_remainder_immediately_claimable(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9105
    await _ingest(
        agent_runtime_uow_factory,
        chat_id=chat_id,
        key="bounded-cont",
        message_ids=[1, 2, 3, 4],
    )

    service = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        coordinator=AlwaysNew(),
        settings=_settings(coordination_message_batch_size=2),
    )

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="w1",
        )
        token1 = claimed[0].claim_token

    result1 = service.process_conversation(chat_id=chat_id, claim_token=token1)
    assert result1.processed == 2

    with agent_runtime_sync_sessionmaker() as session:
        events = list(
            session.scalars(
                select(OutboxEvent).order_by(OutboxEvent.message_id)
            ).all()
        )
        statuses = [e.status for e in events]
        # Unprocessed events remain pending and available (not stuck processing).
        assert statuses == [
            OutboxEventStatus.PUBLISHED,
            OutboxEventStatus.PUBLISHED,
            OutboxEventStatus.PENDING,
            OutboxEventStatus.PENDING,
        ]
        assert all(
            e.available_at <= utcnow()
            for e in events
            if e.status == OutboxEventStatus.PENDING
        )

    with agent_runtime_sync_uow_factory() as uow:
        claimed2 = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="w2",
        )
        assert len(claimed2) == 1
        token2 = claimed2[0].claim_token

    result2 = service.process_conversation(chat_id=chat_id, claim_token=token2)
    assert result2.processed == 2

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage).order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert all(m.coordination_status == CoordinationStatus.GROUPED for m in messages)
