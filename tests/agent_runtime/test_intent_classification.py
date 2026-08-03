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
from telegram_agent.core.agent_runtime.common.models import IntentClassificationDecision
from telegram_agent.core.agent_runtime.common.settings import Settings
from telegram_agent.core.agent_runtime.common.types import (
    ClaimStatus,
    CoordinationStatus,
    MessageIntent,
    OutboxEventStatus,
    OutboxEventType,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    ConversationClaim,
    OutboxEvent,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.agent_runtime.services.sync_intent_classification import (
    SyncIntentClassificationService,
)
from telegram_agent.core.agent_runtime.services.sync_message_group_coordination import (
    SyncMessageGroupCoordinationService,
)
from telegram_agent.core.common.exceptions import PermanentAgentRuntimeCoordinationError
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.llm_gateway.common.schemas import IntentKind
from telegram_agent.core.agent_runtime.clients.models import (
    LlmGatewayGeneration,
    LlmGatewayTokenUsage,
)


def _settings(**overrides) -> Settings:
    values = {
        "sqlalchemy_database_url": "postgresql://unused",
        "coordination_message_batch_size": 10,
        "coordination_recent_window_size": 10,
        "coordination_claim_lease_seconds": 300,
        "outbox_dispatch_lease_seconds": 60,
        "outbox_retry_base_seconds": 5,
        "outbox_retry_max_seconds": 40,
        "outbox_max_attempts": 5,
    }
    values.update(overrides)
    return Settings(**values)



class FixedIntentGateway:
    def __init__(self, intent: IntentKind = IntentKind.CONVERSATION) -> None:
        self.intent = intent
        self.calls: list[dict] = []
        self.fail: Exception | None = None

    def classify_intent(self, **request) -> LlmGatewayGeneration:
        self.calls.append(request)
        if self.fail is not None:
            raise self.fail
        decision = IntentClassificationDecision(intent=self.intent)
        return LlmGatewayGeneration(
            request_id="intent-request",
            output=decision.model_dump(mode="json"),
            provider="test",
            model="test-model",
            usage=LlmGatewayTokenUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )


async def _ingest_coordinate_and_claim_intent(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker,
    *,
    chat_id: int,
    text: str = "hello",
    key: str = "intent-seed",
) -> UUID:
    """Seed a grouped message with a synthetic INTENT outbox for service unit tests.

    The live pipeline no longer emits intent events (it goes straight to download).
    These tests keep exercising SyncIntentClassificationService in isolation.
    """
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
                    text=text,
                ),
            ),
        )
    )
    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="coord-worker",
        )
        claim_token = claimed[0].claim_token

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    # Replace post-group download outbox with intent outbox for isolated service tests.
    with agent_runtime_sync_sessionmaker() as session:
        from sqlalchemy import select
        from telegram_agent.core.agent_runtime.db.models.runtime import OutboxEvent, RuntimeMessage
        message = session.scalars(
            select(RuntimeMessage).where(RuntimeMessage.chat_id == chat_id)
        ).one()
        for event in session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.runtime_message_id == message.id,
                OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
            )
        ).all():
            session.delete(event)
        session.add(
            OutboxEvent(
                event_type=OutboxEventType.INTENT_CLASSIFIER.value,
                chat_id=chat_id,
                runtime_message_id=message.id,
                message_id=message.message_id,
                idempotency_key=f"agent_runtime:intent_classifier:{message.ingress_message_id}:v1",
                payload={
                    "ingress_message_id": str(message.ingress_message_id),
                    "chat_id": chat_id,
                    "message_id": message.message_id,
                    "group_id": str(message.group_id) if message.group_id else None,
                },
            )
        )
        session.commit()

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="intent-worker",
        )
        assert len(claimed) == 1
        return claimed[0].claim_token


@pytest.mark.asyncio
async def test_intent_classifier_marks_classified_and_publishes_outbox(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9201
    claim_token = await _ingest_coordinate_and_claim_intent(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        agent_runtime_sync_sessionmaker,
        chat_id=chat_id,
        text="how are you?",
    )

    gateway = FixedIntentGateway(IntentKind.CONVERSATION)
    result = SyncIntentClassificationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 1
    assert result.results[0].status == RuntimeMessageStatus.CLASSIFIED.value
    assert result.results[0].intent == MessageIntent.CONVERSATION.value
    assert len(gateway.calls) == 1

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        intent_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.INTENT_CLASSIFIER.value
            )
        ).one()
        claim = session.get(ConversationClaim, chat_id)

    assert message.coordination_status == CoordinationStatus.GROUPED
    assert message.status == RuntimeMessageStatus.CLASSIFIED
    assert message.intent == MessageIntent.CONVERSATION
    assert intent_event.status == OutboxEventStatus.PUBLISHED
    assert claim is not None
    assert claim.status == ClaimStatus.IDLE


@pytest.mark.asyncio
async def test_intent_classifier_download_request(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9202
    claim_token = await _ingest_coordinate_and_claim_intent(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        agent_runtime_sync_sessionmaker,
        chat_id=chat_id,
        text="download https://example.com/video.mp4",
        key="intent-download",
    )

    result = SyncIntentClassificationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=FixedIntentGateway(IntentKind.DOWNLOAD_REQUEST),  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.results[0].intent == MessageIntent.DOWNLOAD_REQUEST.value
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        download_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
            )
        ).one()
    assert message.intent == MessageIntent.DOWNLOAD_REQUEST
    assert message.status == RuntimeMessageStatus.CLASSIFIED
    assert download_event.status == OutboxEventStatus.PENDING
    assert download_event.runtime_message_id == message.id


@pytest.mark.asyncio
async def test_intent_classifier_permanent_failure(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9203
    claim_token = await _ingest_coordinate_and_claim_intent(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        agent_runtime_sync_sessionmaker,
        chat_id=chat_id,
        key="intent-permanent",
    )

    gateway = FixedIntentGateway()
    gateway.fail = PermanentAgentRuntimeCoordinationError("auth failed")
    result = SyncIntentClassificationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 0
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        intent_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.INTENT_CLASSIFIER.value
            )
        ).one()

    assert message.status == RuntimeMessageStatus.FAILED
    assert message.intent is None
    assert intent_event.status == OutboxEventStatus.FAILED


@pytest.mark.asyncio
async def test_intent_classifier_retryable_failure_backs_off(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9204
    claim_token = await _ingest_coordinate_and_claim_intent(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        agent_runtime_sync_sessionmaker,
        chat_id=chat_id,
        key="intent-retry",
    )

    before = utcnow()
    gateway = FixedIntentGateway()
    gateway.fail = RuntimeError("temporary")
    result = SyncIntentClassificationService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        settings=_settings(outbox_retry_base_seconds=5),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 0
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        intent_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.INTENT_CLASSIFIER.value
            )
        ).one()

    assert message.status == RuntimeMessageStatus.CLASSIFYING
    assert intent_event.status == OutboxEventStatus.PENDING
    assert intent_event.attempt_count == 1
    assert intent_event.available_at > before


@pytest.mark.asyncio
async def test_grouped_message_emits_intent_outbox(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9205
    await AsyncMessageBatchIngestionService(agent_runtime_uow_factory).ingest(
        IngestMessageBatchCommand(
            batch_id=uuid4(),
            chat_id=chat_id,
            idempotency_key="emit-intent",
            messages=(
                IngestMessageCommand(
                    ingress_message_id=uuid4(),
                    telegram_user_id=1,
                    message_id=1,
                    text="hi",
                ),
            ),
        )
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
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=token)

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        events = list(session.scalars(select(OutboxEvent)).all())

    assert message.status == RuntimeMessageStatus.COORDINATED
    assert message.coordination_status == CoordinationStatus.GROUPED
    by_type = {e.event_type: e for e in events}
    assert (
        by_type[OutboxEventType.MESSAGE_PENDING_COORDINATION.value].status
        == OutboxEventStatus.PUBLISHED
    )
    assert (
        by_type[OutboxEventType.DOWNLOAD_HANDLER.value].status
        == OutboxEventStatus.PENDING
    )


def test_intent_prompt_is_small() -> None:
    from telegram_agent.core.agent_runtime.prompts.intent_classification import (
        SYSTEM_PROMPT,
        build_intent_classification_prompts,
    )
    from telegram_agent.core.agent_runtime.common.models import (
        IntentClassifierMessageView,
    )

    assert "conversation" in SYSTEM_PROMPT
    assert "download_request" in SYSTEM_PROMPT
    assert len(SYSTEM_PROMPT) < 500
    prompts = build_intent_classification_prompts(
        message=IntentClassifierMessageView(
            ingress_message_id=uuid4(),
            message_id=1,
            text="hello",
        )
    )
    assert prompts.system_prompt == SYSTEM_PROMPT
    assert "hello" in prompts.user_prompt
