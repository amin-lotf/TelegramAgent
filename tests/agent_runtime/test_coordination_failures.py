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
from telegram_agent.core.agent_runtime.common.models import CoordinatorDecision
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    CoordinatorDecisionKind,
    OutboxEventStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.db.repositories.sync_message import (
    SyncSqlAlchemyRuntimeMessageRepository,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.agent_runtime.services.sync_message_group_coordination import (
    SyncMessageGroupCoordinationService,
)
from telegram_agent.core.common.exceptions import PermanentAgentRuntimeCoordinationError
from telegram_agent.core.common.utils import utcnow
from tests.agent_runtime.llm_gateway_stub import coordinator_gateway


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


async def _ingest_and_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    *,
    chat_id: int,
    messages: tuple[IngestMessageCommand, ...],
    key: str,
) -> UUID:
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key=key,
            messages=messages,
        )
    )
    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="worker",
        )
        assert len(claimed) == 1
        return claimed[0].claim_token


class PermanentCoordinator:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        raise PermanentAgentRuntimeCoordinationError("protocol broken")


class RetryableCoordinator:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        raise RuntimeError("transient boom")


class CaptureWindowCoordinator:
    def __init__(self) -> None:
        self.windows: list[list[int]] = []
        self.step = 0

    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        self.windows.append([item.message_id for item in recent_window])
        self.step += 1
        if self.step == 1:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)
        if self.step == 2:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.VAGUE)
        # After a vague message, window must still only show grouped priors.
        return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)


class ScriptedGroupCoordinator:
    """NEW then EXISTING using the group number from the window."""

    def __init__(self) -> None:
        self.step = 0

    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        self.step += 1
        if self.step == 1:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)
        assert recent_window
        assert recent_window[-1].group_number == 1
        return CoordinatorDecision(
            kind=CoordinatorDecisionKind.EXISTING,
            group_number=recent_window[-1].group_number,
        )


@pytest.mark.asyncio
async def test_permanent_error_marks_outbox_failed_not_retryable(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9001
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="perm-1",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="x",
            ),
        ),
    )

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(PermanentCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        event = session.scalars(select(OutboxEvent)).one()
        message = session.scalars(select(RuntimeMessage)).one()

    assert event.status == OutboxEventStatus.FAILED
    assert event.attempt_count == 1
    # Message advanced so sequential work is not stuck on a dead head.
    assert message.coordination_status == CoordinationStatus.VAGUE


@pytest.mark.asyncio
async def test_stale_claim_cannot_record_retryable_failure(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9002
    old_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="stale-fail",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="x",
            ),
        ),
    )

    with agent_runtime_sync_sessionmaker() as session:
        event = session.scalars(select(OutboxEvent)).one()
        original_attempts = event.attempt_count
        original_available = event.available_at
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        claim.locked_at = utcnow() - timedelta(hours=1)
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        uow.conversation_claims.recover_expired_claims(
            lease_timeout=timedelta(minutes=1)
        )
        new_claims = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="new-owner",
        )
        assert len(new_claims) == 1
        new_token = new_claims[0].claim_token
        assert new_token != old_token

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(RetryableCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=old_token)

    with agent_runtime_sync_sessionmaker() as session:
        event = session.scalars(select(OutboxEvent)).one()
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        # Old task must not mutate outbox or steal the newer claim.
        assert event.attempt_count == original_attempts
        assert event.available_at == original_available
        assert event.status == OutboxEventStatus.PENDING
        assert claim.claim_token == new_token


@pytest.mark.asyncio
async def test_retryable_failure_uses_exponential_backoff(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9003
    settings = _settings(outbox_retry_base_seconds=5, outbox_retry_max_seconds=40)
    service = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(RetryableCoordinator()),
        settings=settings,
    )

    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key="backoff",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="x",
                ),
            ),
        )
    )

    delays: list[timedelta] = []
    for attempt in range(3):
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner=f"w{attempt}",
            )
            assert len(claimed) == 1
            token = claimed[0].claim_token

        before = utcnow()
        with agent_runtime_sync_sessionmaker() as session:
            event_before = session.scalars(select(OutboxEvent)).one()
            attempts_before = event_before.attempt_count

        service.process_conversation(chat_id=chat_id, claim_token=token)

        with agent_runtime_sync_sessionmaker() as session:
            event = session.scalars(select(OutboxEvent)).one()
            assert event.status == OutboxEventStatus.PENDING
            assert event.attempt_count == attempts_before + 1
            expected = min(
                timedelta(seconds=5 * (2**attempts_before)),
                timedelta(seconds=40),
            )
            actual = event.available_at - before
            # Allow small clock skew.
            assert actual >= expected - timedelta(seconds=1)
            delays.append(expected)

        # Make event immediately available for the next claim attempt.
        with agent_runtime_sync_sessionmaker() as session:
            event = session.scalars(select(OutboxEvent)).one()
            event.available_at = utcnow() - timedelta(seconds=1)
            session.commit()

    assert delays[0] == timedelta(seconds=5)
    assert delays[1] == timedelta(seconds=10)
    assert delays[2] == timedelta(seconds=20)


@pytest.mark.asyncio
async def test_vague_messages_excluded_from_recent_window(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 9004
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="vague-window",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="grouped",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="vague",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=3,
                text="after",
            ),
        ),
    )

    capture = CaptureWindowCoordinator()
    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(capture),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    # Windows for messages 1,2,3: [], [1], [1]  — vague message 2 never appears.
    assert capture.windows[0] == []
    assert capture.windows[1] == [1]
    assert capture.windows[2] == [1]


@pytest.mark.asyncio
async def test_recent_window_is_chronological_oldest_to_newest(
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 9005
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="chrono",
        messages=tuple(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=i,
                text=f"m{i}",
            )
            for i in (10, 20, 30, 40)
        ),
    )

    # Group first three so the fourth sees a multi-message window.
    class AlwaysNew:
        def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(coordination_message_batch_size=3),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        repo = SyncSqlAlchemyRuntimeMessageRepository(session)
        window = repo.list_recent_before(
            chat_id=chat_id,
            before_message_id=40,
            limit=10,
        )
    assert [m.message_id for m in window] == [10, 20, 30]


@pytest.mark.asyncio
async def test_same_task_prior_group_visible_to_later_message(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9006
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="same-task-vis",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="first",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="second",
            ),
        ),
    )

    result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(ScriptedGroupCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.results[0].group_number == 1
    assert result.results[1].group_number == 1
    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[0].group_id == messages[1].group_id
