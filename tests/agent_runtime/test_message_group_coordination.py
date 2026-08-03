from __future__ import annotations

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
from telegram_agent.core.agent_runtime.common.types import (
    CoordinationStatus,
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
from telegram_agent.core.common.exceptions import (
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import utcnow


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


def _service(uow_factory, **settings_overrides) -> SyncMessageGroupCoordinationService:
    return SyncMessageGroupCoordinationService(
        uow_factory=uow_factory,
        settings=_settings(**settings_overrides),
    )


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


def _attachment(
    *,
    type: TelegramAttachmentType,
    file_id: str = "file",
) -> IngestAttachmentCommand:
    return IngestAttachmentCommand(
        ingress_attachment_id=uuid4(),
        type=type,
        status="ready",
        file_id=file_id,
    )


@pytest.mark.asyncio
async def test_first_text_starts_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5001
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="first-text",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="hello",
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert result.processed == 1
    assert result.results[0].status == CoordinationStatus.GROUPED.value
    assert result.results[0].group_number == 1

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        events = list(session.scalars(select(OutboxEvent)).all())
        claim = session.get(ConversationClaim, chat_id)

    assert message.coordination_status == CoordinationStatus.GROUPED
    assert message.status == RuntimeMessageStatus.COORDINATED
    coordination_events = [
        e
        for e in events
        if e.event_type == OutboxEventType.MESSAGE_PENDING_COORDINATION.value
    ]
    download_events = [
        e for e in events if e.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
    ]
    assert len(coordination_events) == 1
    assert coordination_events[0].status == OutboxEventStatus.PUBLISHED
    assert len(download_events) == 1
    assert download_events[0].status == OutboxEventStatus.PENDING
    assert claim is not None
    assert claim.status.value == "idle"
    assert claim.claim_token is None


@pytest.mark.asyncio
async def test_non_reply_text_joins_latest_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5002
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="text-join-latest",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="start",
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
                text="more",
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert result.processed == 3
    assert [item.group_number for item in result.results] == [1, 1, 1]

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
        groups = list(session.scalars(select(ConversationGroup)).all())

    assert messages[0].group_id == messages[1].group_id == messages[2].group_id
    assert len(groups) == 1


@pytest.mark.asyncio
async def test_exclusive_attachment_always_starts_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    """Non-reply exclusive media starts a new group even after prior text."""
    chat_id = 5003
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="exclusive-new",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="I will send a video",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 2]

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[0].group_id != messages[1].group_id


@pytest.mark.asyncio
async def test_text_after_media_joins_latest_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5004
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="text-after-media",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text="subtitle fa",
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 1]

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[0].group_id == messages[1].group_id


@pytest.mark.asyncio
async def test_second_exclusive_attachment_forces_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5005
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="exclusive-second",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid1"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text=None,
                attachment=_attachment(
                    type=TelegramAttachmentType.DOCUMENT, file_id="doc1"
                ),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_photo_after_video_forces_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5016
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="photo-after-video",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.PHOTO, file_id="photo"),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_voice_after_exclusive_joins_latest(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5007
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="voice-after-video",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VOICE, file_id="voice"),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 1]


@pytest.mark.asyncio
async def test_reply_assigns_target_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5101
    # Two exclusive attachments create two groups; reply to the older one joins it.
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="reply-assign",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="v1"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="v2"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=30,
                text="reply to older",
                reply_message_id=10,
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 2, 1]

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[2].group_id == messages[0].group_id
    assert messages[2].group_id != messages[1].group_id


@pytest.mark.asyncio
async def test_reply_to_missing_message_starts_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5102
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="reply-missing",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="hello",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="reply to nowhere",
                reply_message_id=9999,
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    # First text → group 1; missing reply target → new group 2.
    assert [item.group_number for item in result.results] == [1, 2]


@pytest.mark.asyncio
async def test_reply_exclusive_conflict_forces_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
) -> None:
    chat_id = 5107
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="reply-exclusive",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text=None,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text="later",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=30,
                text=None,
                reply_message_id=10,
                attachment=_attachment(type=TelegramAttachmentType.AUDIO, file_id="audio"),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    # Video → g1; text joins g1; reply+audio into exclusive group → new g2.
    assert [item.group_number for item in result.results] == [1, 1, 2]


@pytest.mark.asyncio
async def test_reply_exclusive_into_text_only_group_joins(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5108
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="reply-exclusive-join",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=10,
                text="please process this",
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=20,
                text=None,
                reply_message_id=10,
                attachment=_attachment(type=TelegramAttachmentType.VIDEO, file_id="vid"),
            ),
        ),
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert [item.group_number for item in result.results] == [1, 1]

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(
            session.scalars(
                select(RuntimeMessage)
                .where(RuntimeMessage.chat_id == chat_id)
                .order_by(RuntimeMessage.message_id)
            ).all()
        )
    assert messages[0].group_id == messages[1].group_id


@pytest.mark.asyncio
async def test_standalone_attachment_starts_new_group(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5013
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
                attachment=_attachment(type=TelegramAttachmentType.PHOTO, file_id="photo"),
            ),
        ),
    )

    _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

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

    result = _service(
        agent_runtime_sync_uow_factory,
        coordination_message_batch_size=2,
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

    service = _service(agent_runtime_sync_uow_factory)
    stale_result = service.process_conversation(chat_id=chat_id, claim_token=old_token)
    assert stale_result.processed == 0

    with agent_runtime_sync_sessionmaker() as session:
        claim = session.get(ConversationClaim, chat_id)
        message = session.scalars(select(RuntimeMessage)).one()
        assert claim is not None
        assert claim.claim_token == new_token
        assert claim.status.value == "claimed"
        assert message.coordination_status == CoordinationStatus.PENDING

    fresh_result = service.process_conversation(chat_id=chat_id, claim_token=new_token)
    assert fresh_result.processed == 1


@pytest.mark.asyncio
async def test_retryable_failure_keeps_message_pending_and_releases_claim(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
    monkeypatch,
) -> None:
    chat_id = 5017
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

    def boom(*args, **kwargs):
        raise RetryableAgentRuntimeCoordinationError("transient boom")

    monkeypatch.setattr(
        SyncMessageGroupCoordinationService,
        "_apply_decision",
        boom,
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

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
async def test_permanent_failure_marks_vague(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
    monkeypatch,
) -> None:
    chat_id = 5015
    claim_token = await _ingest_and_claim(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="perm-fail",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text="x",
            ),
        ),
    )

    def boom(*args, **kwargs):
        raise PermanentAgentRuntimeCoordinationError("hard fail")

    monkeypatch.setattr(
        SyncMessageGroupCoordinationService,
        "_apply_decision",
        boom,
    )

    result = _service(agent_runtime_sync_uow_factory).process_conversation(
        chat_id=chat_id, claim_token=claim_token
    )

    assert result.processed == 0
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        event = session.scalars(select(OutboxEvent)).one()

    assert message.coordination_status == CoordinationStatus.VAGUE
    assert event.status == OutboxEventStatus.FAILED


@pytest.mark.asyncio
async def test_does_not_coordinate_same_message_twice(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 5006
    service = _service(agent_runtime_sync_uow_factory)

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
    download_events = [
        event
        for event in events
        if event.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
    ]
    assert len(coordination_events) == 1
    assert coordination_events[0].status == OutboxEventStatus.PUBLISHED
    assert len(download_events) == 1
    assert download_events[0].status == OutboxEventStatus.PENDING
