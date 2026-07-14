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
from telegram_agent.core.agent_runtime.services.coordination_outbox_dispatcher import (
    CoordinationOutboxDispatcher,
)
from telegram_agent.core.common.utils import utcnow


class _FakeTask:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.fail = False

    def apply_async(self, *, args, **kwargs) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.calls.append(args)


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
                    text="x",
                ),
            ),
        )
    )


def _dispatcher(uow_factory, task: _FakeTask) -> CoordinationOutboxDispatcher:
    return CoordinationOutboxDispatcher(
        uow_factory=uow_factory,
        coordinate_task=task,  # type: ignore[arg-type]
        batch_size=10,
        claim_lease_timeout=timedelta(minutes=5),
        outbox_lease_timeout=timedelta(minutes=1),
        retry_base_delay=timedelta(seconds=5),
        retry_max_delay=timedelta(minutes=5),
        process_owner="dispatcher-1",
    )


@pytest.mark.asyncio
async def test_dispatcher_claims_distinct_chats_and_enqueues_tokens(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    for chat_id in (7001, 7002):
        await _seed(agent_runtime_uow_factory, chat_id, f"dispatch-{chat_id}")

    task = _FakeTask()
    result = _dispatcher(agent_runtime_sync_uow_factory, task).dispatch_once()

    assert result.claimed == 2
    assert result.published == 2
    assert result.retryable_failures == 0
    enqueued_chats = {args[0] for args in task.calls}
    assert enqueued_chats == {7001, 7002}
    assert all(args[1] for args in task.calls)  # claim tokens present


@pytest.mark.asyncio
async def test_dispatcher_releases_claim_on_broker_failure(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 7101
    await _seed(agent_runtime_uow_factory, chat_id, "broker-fail")

    task = _FakeTask()
    task.fail = True
    before = utcnow()
    result = _dispatcher(agent_runtime_sync_uow_factory, task).dispatch_once()

    assert result.claimed == 1
    assert result.published == 0
    assert result.retryable_failures == 1

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        assert claim.status == ClaimStatus.IDLE
        assert claim.claim_token is None
        assert claim.available_at > before


@pytest.mark.asyncio
async def test_dispatcher_recovers_expired_claims_before_claiming(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 7201
    await _seed(agent_runtime_uow_factory, chat_id, "recover-dispatch")

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        assert claim is not None
        claim.status = ClaimStatus.CLAIMED
        claim.locked_by = "dead-worker"
        claim.claim_token = uuid4()
        claim.locked_at = utcnow() - timedelta(minutes=30)
        session.commit()

    task = _FakeTask()
    result = _dispatcher(agent_runtime_sync_uow_factory, task).dispatch_once()

    assert result.claimed == 1
    assert result.published == 1
    assert task.calls[0][0] == chat_id
    assert task.calls[0][1]  # new claim token string
