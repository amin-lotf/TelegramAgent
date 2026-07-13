from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_ingress.common.types import (
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.repositories.sync_outbox import (
    SyncSqlAlchemyConversationOutboxRepository,
)


def test_claimed_event_is_skipped_by_concurrent_publisher(
    ingress_sync_sessionmaker: sessionmaker[Session],
) -> None:
    event_id = _seed_event(ingress_sync_sessionmaker)
    first_session = ingress_sync_sessionmaker()
    second_session = ingress_sync_sessionmaker()
    try:
        first_repository = SyncSqlAlchemyConversationOutboxRepository(first_session)
        second_repository = SyncSqlAlchemyConversationOutboxRepository(second_session)

        first_claim = first_repository.claim_available(
            batch_size=10,
            lease_owner="publisher-1",
            lease_timeout=timedelta(minutes=1),
        )
        second_claim = second_repository.claim_available(
            batch_size=10,
            lease_owner="publisher-2",
            lease_timeout=timedelta(minutes=1),
        )

        assert [event.id for event in first_claim] == [event_id]
        assert second_claim == []
    finally:
        first_session.rollback()
        second_session.rollback()
        first_session.close()
        second_session.close()


def test_expired_processing_lease_is_recovered(
    ingress_sync_sessionmaker: sessionmaker[Session],
) -> None:
    event_id = _seed_event(
        ingress_sync_sessionmaker,
        status=OutboxEventStatus.PROCESSING,
        locked_at=utcnow() - timedelta(minutes=10),
        locked_by="dead-publisher",
    )

    with ingress_sync_sessionmaker() as session:
        repository = SyncSqlAlchemyConversationOutboxRepository(session)
        recovered = repository.recover_expired_leases(
            lease_timeout=timedelta(minutes=1),
        )
        session.commit()
        event = session.get(ConversationOutboxEvent, event_id)

    assert recovered == 1
    assert event is not None
    assert event.status == OutboxEventStatus.PENDING
    assert event.locked_at is None
    assert event.locked_by is None


def test_later_batch_for_same_chat_waits_for_earlier_unfinished_batch(
    ingress_sync_sessionmaker: sessionmaker[Session],
) -> None:
    first_id = _seed_event(ingress_sync_sessionmaker, first_message_id=10)
    second_id = _seed_event(ingress_sync_sessionmaker, first_message_id=20)

    with ingress_sync_sessionmaker() as session:
        repository = SyncSqlAlchemyConversationOutboxRepository(session)
        first_claim = repository.claim_available(
            batch_size=10,
            lease_owner="publisher-1",
            lease_timeout=timedelta(minutes=1),
        )
        assert [event.id for event in first_claim] == [first_id]
        repository.mark_published(
            event_id=first_id,
            lease_owner="publisher-1",
        )
        session.commit()

    with ingress_sync_sessionmaker() as session:
        repository = SyncSqlAlchemyConversationOutboxRepository(session)
        second_claim = repository.claim_available(
            batch_size=10,
            lease_owner="publisher-2",
            lease_timeout=timedelta(minutes=1),
        )

    assert [event.id for event in second_claim] == [second_id]


def _seed_event(
    sessionmaker_: sessionmaker[Session],
    *,
    first_message_id: int = 10,
    status: OutboxEventStatus = OutboxEventStatus.PENDING,
    locked_at=None,
    locked_by: str | None = None,
):
    event_id = uuid4()
    with sessionmaker_() as session:
        session.add(
            ConversationOutboxEvent(
                id=event_id,
                event_type=OutboxEventType.CONVERSATION_MESSAGES_ENQUEUED,
                chat_id=900100,
                first_message_id=first_message_id,
                idempotency_key=f"repository-test:{event_id}",
                payload={"chat_id": 900100, "messages": []},
                status=status,
                available_at=utcnow() - timedelta(seconds=1),
                locked_at=locked_at,
                locked_by=locked_by,
            )
        )
        session.commit()
    return event_id
