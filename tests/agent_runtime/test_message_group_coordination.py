from __future__ import annotations

from contextlib import contextmanager
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.agent_runtime.common.commands import (
    IngestAttachmentCommand,
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.settings import Settings
from telegram_agent.core.agent_runtime.common.models import CoordinatorDecision
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
    CoordinatorDecisionKind,
    OutboxEventStatus,
    OutboxEventType,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    ConversationGroup,
    OutboxEvent,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.agent_runtime.services.sync_message_group_coordination import (
    SyncMessageGroupCoordinationService,
)
from telegram_agent.core.common.types import TelegramAttachmentType
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
    }
    values.update(overrides)
    return Settings(**values)


class FailingCoordinator:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        raise RuntimeError("coordinator exploded")


class AdaptiveCoordinator:
    def __init__(self) -> None:
        self.group_number: int | None = None
        self.step = 0

    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        self.step += 1
        if self.step == 1:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)
        if self.step == 2:
            assert recent_window
            self.group_number = recent_window[-1].group_number
            assert self.group_number is not None
            return CoordinatorDecision(
                kind=CoordinatorDecisionKind.EXISTING,
                group_number=self.group_number,
            )
        return CoordinatorDecision(kind=CoordinatorDecisionKind.VAGUE)


class AlwaysNew:
    def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
        return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)


async def _ingest_and_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    *,
    chat_id: int,
    messages: tuple[IngestMessageCommand, ...],
    key: str,
    lease_owner: str = "worker",
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
            process_owner=lease_owner,
        )
        assert len(claimed) == 1
        return claimed[0].claim_token


@pytest.mark.asyncio
async def test_existing_new_and_vague_assignment(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5001
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="coord-1",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="start topic",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text="continue",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=30,
                text="what?",
            ),
        ),
    )

    result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AdaptiveCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 3
    assert result.results[0].status == CoordinationStatus.GROUPED.value
    assert result.results[0].group_number == 1
    assert result.results[1].status == CoordinationStatus.GROUPED.value
    assert result.results[1].group_number == 1
    assert result.results[2].status == CoordinationStatus.VAGUE.value
    assert result.results[2].group_number is None

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
        groups = list(session.scalars(select(ConversationGroup)).all())
        events = list(session.scalars(select(OutboxEvent)).all())
        claim = session.get(ConversationClaim, chat_id)

    assert messages[0].coordination_status == CoordinationStatus.GROUPED
    assert messages[0].status == RuntimeMessageStatus.COORDINATED
    assert messages[1].coordination_status == CoordinationStatus.GROUPED
    assert messages[1].status == RuntimeMessageStatus.COORDINATED
    assert messages[1].group_id == messages[0].group_id
    assert messages[2].coordination_status == CoordinationStatus.VAGUE
    assert messages[2].status == RuntimeMessageStatus.FAILED
    assert messages[2].group_id is None
    assert len(groups) == 1
    assert groups[0].group_number == 1
    coordination_events = [
        event
        for event in events
        if event.event_type == OutboxEventType.MESSAGE_PENDING_COORDINATION.value
    ]
    intent_events = [
        event
        for event in events
        if event.event_type == OutboxEventType.INTENT_CLASSIFIER.value
    ]
    assert len(coordination_events) == 3
    assert all(event.status == OutboxEventStatus.PUBLISHED for event in coordination_events)
    assert len(intent_events) == 2
    assert all(event.status == OutboxEventStatus.PENDING for event in intent_events)
    assert claim is not None
    assert claim.status.value == "idle"
    assert claim.claim_token is None


@pytest.mark.asyncio
async def test_gateway_call_runs_outside_database_transaction(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5011
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="gateway-outside-transaction",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="new topic",
            ),
        ),
    )
    active_transactions = 0

    @contextmanager
    def tracking_uow_factory():
        nonlocal active_transactions
        with agent_runtime_sync_uow_factory() as uow:
            active_transactions += 1
            try:
                yield uow
            finally:
                active_transactions -= 1

    class TransactionAwareDecision:
        def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
            assert active_transactions == 0
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)

    result = SyncMessageGroupCoordinationService(
        uow_factory=tracking_uow_factory,
        llm_gateway_client=coordinator_gateway(TransactionAwareDecision()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 1


@pytest.mark.asyncio
async def test_sequential_group_numbers_per_chat(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5007
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="seq-groups",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="a",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="b",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=3,
                text="c",
            ),
        ),
    )

    result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert [item.group_number for item in result.results] == [1, 2, 3]
    with agent_runtime_sync_sessionmaker() as session:
        numbers = list(
            session.scalars(
                select(ConversationGroup.group_number)
                .where(ConversationGroup.chat_id == chat_id)
                .order_by(ConversationGroup.group_number)
            ).all()
        )
    assert numbers == [1, 2, 3]


@pytest.mark.asyncio
async def test_invalid_group_number_becomes_vague(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    class BadExisting:
        def __init__(self) -> None:
            self.step = 0

        def assign_group(self, *, current, recent_window) -> CoordinatorDecision:
            self.step += 1
            if self.step == 1:
                return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)
            return CoordinatorDecision(
                kind=CoordinatorDecisionKind.EXISTING,
                group_number=999,
            )

    chat_id = 5008
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="bad-group",
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
        llm_gateway_client=coordinator_gateway(BadExisting()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.results[0].group_number == 1
    assert result.results[1].status == CoordinationStatus.VAGUE.value
    with agent_runtime_sync_sessionmaker() as session:
        second = session.scalars(
            select(RuntimeMessage)
            .where(RuntimeMessage.chat_id == chat_id)
            .order_by(RuntimeMessage.message_id)
        ).all()[1]
    assert second.group_id is None


@pytest.mark.asyncio
async def test_text_followed_by_related_attachment_same_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5002
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="attach-related",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="I will send a video; tell me what it is about",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid",
                ),
            ),
        ),
    )

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AdaptiveCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[0].group_id is not None
    assert messages[1].group_id == messages[0].group_id


@pytest.mark.asyncio
async def test_standalone_attachment_starts_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5003
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="standalone-attach",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.PHOTO,
                    status="ready",
                    file_id="photo",
                ),
            ),
        ),
    )

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(
            select(RuntimeMessage).where(RuntimeMessage.chat_id == chat_id)
        ).one()
        group = session.get(ConversationGroup, message.group_id)
    assert message.coordination_status == CoordinationStatus.GROUPED
    assert group is not None
    assert group.group_number == 1


@pytest.mark.asyncio
async def test_bounded_task_leaves_remainder_pending(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5009
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="bounded",
        messages=tuple(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=i,
                text=f"m{i}",
            )
            for i in range(1, 6)
        ),
    )

    result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(coordination_message_batch_size=2),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 2
    with agent_runtime_sync_sessionmaker() as session:
        statuses = list(
            session.scalars(
                select(RuntimeMessage.coordination_status)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert statuses[:2] == [CoordinationStatus.GROUPED, CoordinationStatus.GROUPED]
    assert statuses[2:] == [
        CoordinationStatus.PENDING,
        CoordinationStatus.PENDING,
        CoordinationStatus.PENDING,
    ]


@pytest.mark.asyncio
async def test_stale_claim_token_cannot_process_or_release(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5010
    old_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="stale-token",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="x",
            ),
        ),
        lease_owner="old",
    )

    # Expire and re-claim with a new token.
    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        claim.locked_at = utcnow() - timedelta(hours=1)
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        recovered = uow.conversation_claims.recover_expired_claims(
            lease_timeout=timedelta(minutes=1)
        )
        assert recovered == 1
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="new",
        )
        assert len(claimed) == 1
        new_token = claimed[0].claim_token

    stale_result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=old_token)
    assert stale_result.processed == 0

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        message = session.scalars(select(RuntimeMessage)).one()
        assert claim is not None
        assert claim.claim_token == new_token
        assert claim.status.value == "claimed"
        assert message.coordination_status == CoordinationStatus.PENDING

    fresh_result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=new_token)
    assert fresh_result.processed == 1


@pytest.mark.asyncio
async def test_coordinator_failure_keeps_message_pending_and_releases_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5005
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="fail-coord",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="will fail",
            ),
        ),
    )

    result = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(FailingCoordinator()),
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 0
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(
            select(RuntimeMessage).where(RuntimeMessage.chat_id == chat_id)
        ).one()
        event = session.scalars(select(OutboxEvent)).one()
        claim = session.get(ConversationClaim, chat_id)

    assert message.coordination_status == CoordinationStatus.PENDING
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 1
    assert event.available_at > utcnow()
    assert claim is not None
    assert claim.status.value == "idle"
    assert claim.claim_token is None


@pytest.mark.asyncio
async def test_does_not_coordinate_same_message_twice(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5006
    service = SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=coordinator_gateway(AlwaysNew()),
        settings=_settings(),
    )

    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key="twice",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="once",
                ),
            ),
        )
    )

    for owner in ("w1", "w2"):
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner=owner,
            )
        if not claimed:
            continue
        service.process_conversation(
            chat_id=chat_id,
            claim_token=claimed[0].claim_token,
        )

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(session.scalars(select(RuntimeMessage)).all())
        events = list(session.scalars(select(OutboxEvent)).all())

    assert len(messages) == 1
    assert messages[0].coordination_status == CoordinationStatus.GROUPED
    assert messages[0].status == RuntimeMessageStatus.COORDINATED
    coordination_events = [
        event
        for event in events
        if event.event_type == OutboxEventType.MESSAGE_PENDING_COORDINATION.value
    ]
    intent_events = [
        event
        for event in events
        if event.event_type == OutboxEventType.INTENT_CLASSIFIER.value
    ]
    assert len(coordination_events) == 1
    assert coordination_events[0].status == OutboxEventStatus.PUBLISHED
    assert len(intent_events) == 1
    assert intent_events[0].status == OutboxEventStatus.PENDING
