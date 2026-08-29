from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import (
    AgentRuntimeBadResponseError,
    AgentRuntimeUnavailableError,
)
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_ingress.common.types import (
    ConversationStatus,
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.telegram_ingress.db.models.outbox import ConversationOutboxEvent
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage
from telegram_agent.core.telegram_ingress.services.outbox_publisher import OutboxPublisher
from telegram_agent.core.telegram_ingress.clients.schemas import (
    CancelAllSecondaryTasksResponse,
)


class AcceptingAgentRuntimeClient:
    def __init__(self) -> None:
        self.calls = []

    def submit_message_batch(self, **kwargs) -> None:
        self.calls.append(kwargs)


class UnavailableAgentRuntimeClient:
    def submit_message_batch(self, **kwargs) -> None:
        raise AgentRuntimeUnavailableError("runtime unavailable")


class RejectingAgentRuntimeClient:
    def submit_message_batch(self, **kwargs) -> None:
        raise AgentRuntimeBadResponseError("invalid batch")


class AcceptingCancellationClient:
    def __init__(self) -> None:
        self.calls = []

    def cancel_all_secondary_tasks(self, **kwargs):
        self.calls.append(kwargs)
        return CancelAllSecondaryTasksResponse(
            status="registered",
            cancellation_id=uuid4(),
            cutoff_message_id=20,
            matched_active_count=2,
        )


class RecordingTelegramBotClient:
    def __init__(self) -> None:
        self.calls = []

    def send_message(self, **kwargs) -> int:
        self.calls.append(kwargs)
        return 99


def test_success_marks_outbox_published_and_messages_dispatched(
    ingress_sync_sessionmaker: sessionmaker[Session],
    ingress_sync_uow_factory,
) -> None:
    event_id, message_id = _seed_batch(ingress_sync_sessionmaker)
    client = AcceptingAgentRuntimeClient()

    result = _publisher(ingress_sync_uow_factory, client).dispatch_once()

    with ingress_sync_sessionmaker() as session:
        event = session.get(ConversationOutboxEvent, event_id)
        message = session.get(UserMessage, message_id)

    assert result.published == 1
    assert len(client.calls) == 1
    assert client.calls[0]["batch_id"] == event_id
    assert event is not None
    assert message is not None
    assert event.status == OutboxEventStatus.PUBLISHED
    assert event.published_at is not None
    assert message.conversation_status == ConversationStatus.DISPATCHED


def test_unavailable_runtime_schedules_retry_and_keeps_messages_enqueued(
    ingress_sync_sessionmaker: sessionmaker[Session],
    ingress_sync_uow_factory,
) -> None:
    event_id, message_id = _seed_batch(ingress_sync_sessionmaker)

    result = _publisher(
        ingress_sync_uow_factory,
        UnavailableAgentRuntimeClient(),
    ).dispatch_once()

    with ingress_sync_sessionmaker() as session:
        event = session.get(ConversationOutboxEvent, event_id)
        message = session.get(UserMessage, message_id)

    assert result.retryable_failures == 1
    assert event is not None
    assert message is not None
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 1
    assert event.last_error == "runtime unavailable"
    assert message.conversation_status == ConversationStatus.ENQUEUED


def test_permanent_rejection_fails_outbox_and_included_messages(
    ingress_sync_sessionmaker: sessionmaker[Session],
    ingress_sync_uow_factory,
) -> None:
    event_id, message_id = _seed_batch(ingress_sync_sessionmaker)

    result = _publisher(
        ingress_sync_uow_factory,
        RejectingAgentRuntimeClient(),
    ).dispatch_once()

    with ingress_sync_sessionmaker() as session:
        event = session.get(ConversationOutboxEvent, event_id)
        message = session.get(UserMessage, message_id)

    assert result.permanent_failures == 1
    assert event is not None
    assert message is not None
    assert event.status == OutboxEventStatus.FAILED
    assert event.attempt_count == 1
    assert event.last_error == "invalid batch"
    assert message.conversation_status == ConversationStatus.FAILED


def test_cancel_all_outbox_calls_content_processing_and_sends_one_summary(
    ingress_sync_sessionmaker: sessionmaker[Session],
    ingress_sync_uow_factory,
) -> None:
    event_id, message_id = _seed_cancel_all(ingress_sync_sessionmaker)
    cancellation = AcceptingCancellationClient()
    telegram = RecordingTelegramBotClient()
    publisher = OutboxPublisher(
        uow_factory=ingress_sync_uow_factory,
        agent_runtime_client=AcceptingAgentRuntimeClient(),
        content_processing_client=cancellation,  # type: ignore[arg-type]
        telegram_bot_client=telegram,  # type: ignore[arg-type]
        batch_size=10,
        lease_timeout=timedelta(minutes=1),
        retry_base_delay=timedelta(seconds=5),
        retry_max_delay=timedelta(minutes=5),
        lease_owner="test-ingress-publisher",
    )
    result = publisher.dispatch_once()
    with ingress_sync_sessionmaker() as session:
        event = session.get(ConversationOutboxEvent, event_id)
        message = session.get(UserMessage, message_id)
    assert result.published == 1
    assert len(cancellation.calls) == 1
    assert len(telegram.calls) == 1
    assert "2 active" in telegram.calls[0]["text"]
    assert event is not None and event.status == OutboxEventStatus.PUBLISHED
    assert message is not None
    assert message.conversation_status == ConversationStatus.DISPATCHED


def _publisher(uow_factory, client) -> OutboxPublisher:
    return OutboxPublisher(
        uow_factory=uow_factory,
        agent_runtime_client=client,
        batch_size=10,
        lease_timeout=timedelta(minutes=1),
        retry_base_delay=timedelta(seconds=5),
        retry_max_delay=timedelta(minutes=5),
        lease_owner="test-ingress-publisher",
    )


def _seed_batch(
    sessionmaker_: sessionmaker[Session],
) -> tuple:
    event_id = uuid4()
    message_id = uuid4()
    payload = {
        "chat_id": 900100,
        "messages": [
            {
                "ingress_message_id": str(message_id),
                "telegram_user_id": 123456,
                "message_id": 10,
                "reply_message_id": None,
                "text": "dispatch me",
                "attachment": None,
            }
        ],
    }
    with sessionmaker_() as session:
        event = ConversationOutboxEvent(
            id=event_id,
            event_type=OutboxEventType.CONVERSATION_MESSAGES_ENQUEUED,
            chat_id=900100,
            first_message_id=10,
            idempotency_key=f"test-batch:{event_id}",
            payload=payload,
            status=OutboxEventStatus.PENDING,
            available_at=utcnow() - timedelta(seconds=1),
        )
        message = UserMessage(
            id=message_id,
            telegram_user_id=123456,
            chat_id=900100,
            message_id=10,
            update_id=1010,
            text="dispatch me",
            conversation_status=ConversationStatus.ENQUEUED,
            dispatch_event_id=event_id,
        )
        session.add_all([event, message])
        session.commit()
    return event_id, message_id


def _seed_cancel_all(
    sessionmaker_: sessionmaker[Session],
) -> tuple:
    event_id = uuid4()
    message_id = uuid4()
    with sessionmaker_() as session:
        event = ConversationOutboxEvent(
            id=event_id,
            event_type=OutboxEventType.CANCEL_ALL_SECONDARY_TASKS_REQUESTED,
            chat_id=100,
            first_message_id=20,
            idempotency_key=f"cancel-all:{event_id}",
            payload={
                "telegram_user_id": 7,
                "chat_id": 100,
                "command_message_id": 20,
            },
            status=OutboxEventStatus.PENDING,
            available_at=utcnow() - timedelta(seconds=1),
        )
        message = UserMessage(
            id=message_id,
            telegram_user_id=7,
            chat_id=100,
            message_id=20,
            update_id=2020,
            text="/cancel_all",
            conversation_status=ConversationStatus.ENQUEUED,
            dispatch_event_id=event_id,
        )
        session.add_all([event, message])
        session.commit()
    return event_id, message_id
