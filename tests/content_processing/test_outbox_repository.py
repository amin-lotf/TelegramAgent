from __future__ import annotations

from datetime import timedelta

import pytest

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.common.const import CONTENT_PROCESSING_JOB_AGGREGATE_TYPE
from telegram_agent.core.content_processing.common.types import OutboxEventStatus, OutboxEventType
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent
from telegram_agent.core.content_processing.db.repositories.async_outbox import AsyncSqlAlchemyOutboxRepository

pytestmark = pytest.mark.asyncio


async def test_pending_events_can_be_claimed(content_session, content_job_factory) -> None:
    job = await content_job_factory()
    repository = AsyncSqlAlchemyOutboxRepository(content_session)
    event = await repository.add(_outbox_event(job.id))
    await content_session.commit()

    claimed = await repository.claim_available(
        batch_size=10,
        lease_owner="dispatcher-1",
        lease_timeout=timedelta(minutes=1),
    )
    await content_session.commit()

    assert [claimed_event.id for claimed_event in claimed] == [event.id]
    assert claimed[0].status == OutboxEventStatus.PROCESSING
    assert claimed[0].locked_by == "dispatcher-1"
    assert claimed[0].locked_at is not None


async def test_claimed_events_are_skipped_by_concurrent_dispatcher(
    content_sessionmaker,
    content_job_factory,
) -> None:
    job = await content_job_factory()
    async with content_sessionmaker() as seed_session:
        seed_repository = AsyncSqlAlchemyOutboxRepository(seed_session)
        event = await seed_repository.add(_outbox_event(job.id))
        await seed_session.commit()

    session_one = content_sessionmaker()
    session_two = content_sessionmaker()
    try:
        repository_one = AsyncSqlAlchemyOutboxRepository(session_one)
        repository_two = AsyncSqlAlchemyOutboxRepository(session_two)

        first_claim = await repository_one.claim_available(
            batch_size=10,
            lease_owner="dispatcher-1",
            lease_timeout=timedelta(minutes=1),
        )
        second_claim = await repository_two.claim_available(
            batch_size=10,
            lease_owner="dispatcher-2",
            lease_timeout=timedelta(minutes=1),
        )

        assert [claimed_event.id for claimed_event in first_claim] == [event.id]
        assert second_claim == []
    finally:
        await session_one.rollback()
        await session_two.rollback()
        await session_one.close()
        await session_two.close()


async def test_published_events_are_marked_correctly(content_session, content_job_factory) -> None:
    job = await content_job_factory()
    repository = AsyncSqlAlchemyOutboxRepository(content_session)
    event = await repository.add(_outbox_event(job.id))
    await content_session.commit()
    claimed = await repository.claim_available(
        batch_size=1,
        lease_owner="dispatcher-1",
        lease_timeout=timedelta(minutes=1),
    )

    published = await repository.mark_published(
        event_id=claimed[0].id,
        lease_owner="dispatcher-1",
    )
    await content_session.commit()

    assert published is not None
    assert published.id == event.id
    assert published.status == OutboxEventStatus.PUBLISHED
    assert published.published_at is not None
    assert published.locked_at is None
    assert published.locked_by is None


async def test_failed_events_increment_attempts_and_get_future_retry_time(
    content_session,
    content_job_factory,
) -> None:
    job = await content_job_factory()
    repository = AsyncSqlAlchemyOutboxRepository(content_session)
    event = await repository.add(_outbox_event(job.id))
    await content_session.commit()
    original_attempt_count = event.attempt_count
    claimed = await repository.claim_available(
        batch_size=1,
        lease_owner="dispatcher-1",
        lease_timeout=timedelta(minutes=1),
    )
    retry_at = utcnow() + timedelta(seconds=30)

    failed = await repository.record_failure(
        event_id=claimed[0].id,
        lease_owner="dispatcher-1",
        error_message="broker\n unavailable",
        next_available_at=retry_at,
    )
    await content_session.commit()

    assert failed is not None
    assert failed.status == OutboxEventStatus.PENDING
    assert failed.attempt_count == original_attempt_count + 1
    assert failed.available_at >= retry_at
    assert failed.locked_at is None
    assert failed.locked_by is None
    assert failed.last_error == "broker unavailable"


async def test_expired_processing_leases_can_be_reclaimed(content_session, content_job_factory) -> None:
    job = await content_job_factory()
    repository = AsyncSqlAlchemyOutboxRepository(content_session)
    event = await repository.add(
        _outbox_event(
            job.id,
            status=OutboxEventStatus.PROCESSING,
            locked_by="dead-dispatcher",
            locked_at=utcnow() - timedelta(minutes=10),
        )
    )
    await content_session.commit()

    claimed = await repository.claim_available(
        batch_size=10,
        lease_owner="dispatcher-2",
        lease_timeout=timedelta(minutes=1),
    )
    await content_session.commit()

    assert [claimed_event.id for claimed_event in claimed] == [event.id]
    assert claimed[0].status == OutboxEventStatus.PROCESSING
    assert claimed[0].locked_by == "dispatcher-2"


def _outbox_event(
    job_id,
    *,
    status: OutboxEventStatus = OutboxEventStatus.PENDING,
    locked_by: str | None = None,
    locked_at=None,
) -> OutboxEvent:
    return OutboxEvent(
        event_type=OutboxEventType.CONTENT_PROCESSING_JOB_READY,
        aggregate_type=CONTENT_PROCESSING_JOB_AGGREGATE_TYPE,
        aggregate_id=job_id,
        payload={"job_id": str(job_id)},
        status=status,
        available_at=utcnow() - timedelta(seconds=1),
        locked_by=locked_by,
        locked_at=locked_at,
    )
