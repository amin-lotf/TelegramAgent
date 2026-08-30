from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.agent_runtime.clients.models import (
    LlmGatewayGeneration,
    LlmGatewayTokenUsage,
)
from telegram_agent.core.agent_runtime.common.commands import (
    IngestAttachmentCommand,
    IngestMessageBatchCommand,
    IngestMessageCommand,
)
from telegram_agent.core.agent_runtime.common.models import DownloadAgentDecision
from telegram_agent.core.agent_runtime.common.settings import Settings
from telegram_agent.core.agent_runtime.common.types import (
    AgentMessageRole,
    ClaimStatus,
    OutboxEventStatus,
    OutboxEventType,
    RuntimeMessageStatus,
)
from telegram_agent.core.agent_runtime.db.models.runtime import (
    AgentMessage,
    ConversationClaim,
    OutboxEvent,
    RuntimeMessage,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)
from telegram_agent.core.agent_runtime.services.sync_content_processing_handoff import (
    SyncContentProcessingHandoffService,
)
from telegram_agent.core.agent_runtime.services.sync_download_handler import (
    SyncDownloadHandlerService,
)
from telegram_agent.core.agent_runtime.services.sync_message_group_coordination import (
    SyncMessageGroupCoordinationService,
)
from telegram_agent.core.common.exceptions import (
    RetryableAgentRuntimeCoordinationError,
    TelegramIngressUnavailableError,
)
from telegram_agent.core.common.types import TelegramAttachmentType


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


class FixedDownloadGateway:
    def __init__(
        self,
        *,
        assistant_text: str = "Preparing your video download.",
        subtitle: str | None = "en",
        dub: str | None = None,
        is_download_request: bool = True,
    ) -> None:
        self.assistant_text = assistant_text
        self.subtitle = subtitle
        self.dub = dub
        self.is_download_request = is_download_request
        self.calls: list[dict] = []
        self.fail: Exception | None = None

    def extract_download_request(self, **request) -> LlmGatewayGeneration:
        self.calls.append(request)
        if self.fail is not None:
            raise self.fail
        decision = DownloadAgentDecision(
            is_download_request=self.is_download_request,
            assistant_text=self.assistant_text,
            requested_subtitle_language=self.subtitle,
            requested_dub_language=self.dub,
        )
        return LlmGatewayGeneration(
            request_id="download-request",
            output=decision.model_dump(mode="json"),
            provider="test",
            model="test-model",
            usage=LlmGatewayTokenUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )


class RecordingTelegramClient:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def notify_user(self, **kwargs) -> None:
        self.calls.append(kwargs)
        if self.fail is not None:
            raise self.fail

    def notify_request_preparing(self, **kwargs) -> None:
        self.notify_user(**kwargs)


class RecordingContentProcessingClient:
    def __init__(self, *, fail: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def submit_video_download(self, **kwargs) -> None:
        self.calls.append({"method": "video", **kwargs})
        if self.fail is not None:
            raise self.fail

    def submit_audio_download(self, **kwargs) -> None:
        self.calls.append({"method": "audio", **kwargs})
        if self.fail is not None:
            raise self.fail

    def submit_document_download(self, **kwargs) -> None:
        self.calls.append({"method": "document", **kwargs})
        if self.fail is not None:
            raise self.fail


async def _ingest_coordinate_classify_download(
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
            process_owner="coord-worker",
        )
        claim_token = claimed[0].claim_token

    SyncMessageGroupCoordinationService(
        uow_factory=agent_runtime_sync_uow_factory,
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="download-worker",
        )
        assert len(claimed) == 1
        return claimed[0].claim_token


@pytest.mark.asyncio
async def test_download_handler_early_exit_media_only(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9301
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-media-only",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=7,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-1",
                ),
            ),
        ),
    )

    gateway = FixedDownloadGateway()
    telegram = RecordingTelegramClient()
    result = SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=telegram,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed == 1
    assert result.results[0].early_exit is True
    assert len(gateway.calls) == 0
    assert len(telegram.calls) == 0

    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        download_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
            )
        ).one()
        agent_messages = list(session.scalars(select(AgentMessage)).all())
        handoff = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
            ).all()
        )
        claim = session.get(ConversationClaim, chat_id)

    assert message.status == RuntimeMessageStatus.COORDINATED
    assert download_event.status == OutboxEventStatus.PUBLISHED
    assert agent_messages == []
    assert handoff == []
    assert claim is not None
    assert claim.status == ClaimStatus.IDLE


@pytest.mark.asyncio
async def test_download_handler_early_exit_text_only(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9302
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-text-only",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=7,
                message_id=1,
                text="please download with english subtitles",
            ),
        ),
    )

    result = SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=FixedDownloadGateway(),  # type: ignore[arg-type]
        telegram_ingress_client=RecordingTelegramClient(),  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.results[0].early_exit is True
    with agent_runtime_sync_sessionmaker() as session:
        message = session.scalars(select(RuntimeMessage)).one()
        download_event = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
            )
        ).one()
        assert list(session.scalars(select(AgentMessage)).all()) == []

    assert message.status == RuntimeMessageStatus.COORDINATED
    assert download_event.status == OutboxEventStatus.PUBLISHED


@pytest.mark.asyncio
async def test_download_handler_happy_path_and_handoff(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9303
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-happy",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=9,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-happy",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=9,
                message_id=2,
                text="english subtitles please",
            ),
        ),
    )

    gateway = FixedDownloadGateway(assistant_text="Got it — preparing your download.")
    telegram = RecordingTelegramClient()
    result = SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=telegram,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    # Head-of-line: first message may early-exit if processed alone; process all
    # download_handler events under sequential claims until handoff exists.
    assert result.processed >= 1

    # Drain remaining download_handler events (second message).
    for _ in range(3):
        with agent_runtime_sync_sessionmaker() as session:
            pending = list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                    )
                ).all()
            )
        if not pending:
            break
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner="download-worker-2",
            )
            if not claimed:
                break
            token = claimed[0].claim_token
        SyncDownloadHandlerService(
            uow_factory=agent_runtime_sync_uow_factory,
            llm_gateway_client=gateway,  # type: ignore[arg-type]
            telegram_ingress_client=telegram,  # type: ignore[arg-type]
            settings=_settings(),
        ).process_conversation(chat_id=chat_id, claim_token=token)

    with agent_runtime_sync_sessionmaker() as session:
        agent_messages = list(session.scalars(select(AgentMessage)).all())
        handoff_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
            ).all()
        )
        messages = list(session.scalars(select(RuntimeMessage)).all())

    assert len(agent_messages) == 1
    assert agent_messages[0].role == AgentMessageRole.DOWNLOAD_AGENT
    assert agent_messages[0].text == "Got it — preparing your download."
    assert agent_messages[0].chat_id == chat_id
    assert len(handoff_events) == 1
    assert handoff_events[0].status == OutboxEventStatus.PENDING
    # At least the download-handler head message remains coordinated (not failed).
    coordinated = [m for m in messages if m.status == RuntimeMessageStatus.COORDINATED]
    assert len(coordinated) >= 1
    assert all(m.status != RuntimeMessageStatus.FAILED for m in messages)
    assert len(gateway.calls) == 1
    assert str(gateway.calls[0]["idempotency_key"]).startswith("download-agent:")
    assert len(telegram.calls) == 1
    assert telegram.calls[0]["text"] == "Got it — preparing your download."
    assert telegram.calls[0]["reply_to_message_id"] is not None
    assert handoff_events[0].payload.get("reply_to_message_id") is not None

    # Placeholder content-processing handoff.
    with agent_runtime_sync_uow_factory() as uow:
        claimed = uow.conversation_claims.claim_available_conversations(
            batch_size=1,
            lease_timeout=timedelta(minutes=5),
            process_owner="handoff-worker",
        )
        handoff_token = claimed[0].claim_token

    cp_client = RecordingContentProcessingClient()
    handoff_result = SyncContentProcessingHandoffService(
        uow_factory=agent_runtime_sync_uow_factory,
        content_processing_client=cp_client,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=handoff_token)

    assert handoff_result.processed == 1
    assert len(cp_client.calls) == 1
    assert cp_client.calls[0]["method"] == "video"
    assert cp_client.calls[0]["requested_subtitle_language"] == "en"
    assert "assistant_text" in cp_client.calls[0]
    assert cp_client.calls[0].get("reply_to_message_id") is not None

    # Outbox payload stores typed fields at top level for the handoff consumer.
    with agent_runtime_sync_sessionmaker() as session:
        handoff_row = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type
                == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
            )
        ).one()
    assert handoff_row.payload["media_type"] == "video"
    assert handoff_row.payload["requested_subtitle_language"] == "en"
    assert handoff_row.payload.get("assistant_text")
    assert handoff_row.payload.get("reply_to_message_id") is not None

    with agent_runtime_sync_sessionmaker() as session:
        handoff = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.event_type
                == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
            )
        ).one()
    assert handoff.status == OutboxEventStatus.PUBLISHED


@pytest.mark.asyncio
async def test_download_handler_notify_failure_is_best_effort(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9304
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-notify-fail",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-nf",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="dub in persian",
            ),
        ),
    )

    gateway = FixedDownloadGateway(assistant_text="Preparing download.")
    telegram = RecordingTelegramClient(
        fail=TelegramIngressUnavailableError("down"),
    )

    for token in (claim_token,):
        SyncDownloadHandlerService(
            uow_factory=agent_runtime_sync_uow_factory,
            llm_gateway_client=gateway,  # type: ignore[arg-type]
            telegram_ingress_client=telegram,  # type: ignore[arg-type]
            settings=_settings(),
        ).process_conversation(chat_id=chat_id, claim_token=token)

    for _ in range(3):
        with agent_runtime_sync_sessionmaker() as session:
            pending = list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                    )
                ).all()
            )
        if not pending:
            break
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner="dl-nf",
            )
            if not claimed:
                break
            SyncDownloadHandlerService(
                uow_factory=agent_runtime_sync_uow_factory,
                llm_gateway_client=gateway,  # type: ignore[arg-type]
                telegram_ingress_client=telegram,  # type: ignore[arg-type]
                settings=_settings(),
            ).process_conversation(chat_id=chat_id, claim_token=claimed[0].claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        agent_messages = list(session.scalars(select(AgentMessage)).all())
        handoff = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
            ).all()
        )

    assert len(agent_messages) == 1
    assert len(handoff) == 1
    assert len(telegram.calls) == 1


@pytest.mark.asyncio
async def test_download_handler_retryable_llm_failure(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9305
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-retry",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-retry",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="english subs",
            ),
        ),
    )

    gateway = FixedDownloadGateway()
    gateway.fail = RetryableAgentRuntimeCoordinationError("llm busy")

    # Process until we hit the complete-group head (may early-exit first msg).
    SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=RecordingTelegramClient(),  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    for _ in range(3):
        with agent_runtime_sync_sessionmaker() as session:
            pending = list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                    )
                ).all()
            )
        if not pending:
            break
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner="dl-retry",
            )
            if not claimed:
                break
            SyncDownloadHandlerService(
                uow_factory=agent_runtime_sync_uow_factory,
                llm_gateway_client=gateway,  # type: ignore[arg-type]
                telegram_ingress_client=RecordingTelegramClient(),  # type: ignore[arg-type]
                settings=_settings(),
            ).process_conversation(chat_id=chat_id, claim_token=claimed[0].claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        messages = list(session.scalars(select(RuntimeMessage)).all())
        failed_or_pending = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
                    OutboxEvent.status == OutboxEventStatus.PENDING,
                )
            ).all()
        )
        agent_messages = list(session.scalars(select(AgentMessage)).all())

    assert all(m.status != RuntimeMessageStatus.FAILED for m in messages)
    assert agent_messages == []
    assert len(failed_or_pending) >= 1
    assert any(e.attempt_count >= 1 for e in failed_or_pending)


@pytest.mark.asyncio
async def test_download_handler_idempotent_for_request(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9306
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-idem",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.AUDIO,
                    status="ready",
                    file_id="aud-1",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="transcribe in english",
            ),
        ),
    )

    gateway = FixedDownloadGateway(
        assistant_text="Preparing audio download.",
        subtitle=None,
    )
    # Override video-oriented fields for audio via generic decision.
    gateway = FixedDownloadGateway(assistant_text="Preparing audio download.")

    telegram = RecordingTelegramClient()
    SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=telegram,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    for _ in range(3):
        with agent_runtime_sync_sessionmaker() as session:
            pending = list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value,
                        OutboxEvent.status == OutboxEventStatus.PENDING,
                    )
                ).all()
            )
        if not pending:
            break
        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner="dl-idem",
            )
            if not claimed:
                break
            SyncDownloadHandlerService(
                uow_factory=agent_runtime_sync_uow_factory,
                llm_gateway_client=gateway,  # type: ignore[arg-type]
                telegram_ingress_client=telegram,  # type: ignore[arg-type]
                settings=_settings(),
            ).process_conversation(chat_id=chat_id, claim_token=claimed[0].claim_token)

    with agent_runtime_sync_sessionmaker() as session:
        agent_messages = list(session.scalars(select(AgentMessage)).all())
        handoff = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
            ).all()
        )
        download_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
                )
            ).all()
        )

    assert len(agent_messages) == 1
    assert len(handoff) == 1
    assert all(e.status == OutboxEventStatus.PUBLISHED for e in download_events)
    # The media-only message is not a request; the single text request runs once.
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_identical_messages_in_one_group_create_independent_jobs(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9310
    first_request_id = uuid4()
    second_request_id = uuid4()
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-message-scoped-idempotency",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-shared",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=first_request_id,
                telegram_user_id=1,
                message_id=2,
                text="download with english subtitles",
            ),
            IngestMessageCommand(
                ingress_message_id=second_request_id,
                telegram_user_id=1,
                message_id=3,
                text="download with english subtitles",
            ),
        ),
    )

    gateway = FixedDownloadGateway()
    telegram = RecordingTelegramClient()
    content_processing = RecordingContentProcessingClient()
    download_service = SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=telegram,  # type: ignore[arg-type]
        settings=_settings(),
    )
    handoff_service = SyncContentProcessingHandoffService(
        uow_factory=agent_runtime_sync_uow_factory,
        content_processing_client=content_processing,  # type: ignore[arg-type]
        settings=_settings(),
    )

    next_token = claim_token
    for _ in range(5):
        with agent_runtime_sync_uow_factory() as uow:
            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
        if head is None:
            break
        if head.event_type == OutboxEventType.DOWNLOAD_HANDLER.value:
            download_service.process_conversation(
                chat_id=chat_id,
                claim_token=next_token,
            )
        else:
            assert head.event_type == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
            handoff_service.process_conversation(
                chat_id=chat_id,
                claim_token=next_token,
            )

        with agent_runtime_sync_uow_factory() as uow:
            claimed = uow.conversation_claims.claim_available_conversations(
                batch_size=1,
                lease_timeout=timedelta(minutes=5),
                process_owner="message-scoped-worker",
            )
            if not claimed:
                break
            next_token = claimed[0].claim_token

    with agent_runtime_sync_sessionmaker() as session:
        agent_messages = list(
            session.scalars(select(AgentMessage).order_by(AgentMessage.created_at)).all()
        )
        handoffs = list(
            session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
                .order_by(OutboxEvent.message_id)
            ).all()
        )
        download_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
                )
            ).all()
        )

    assert len(agent_messages) == 2
    assert {message.ingress_message_id for message in agent_messages} == {
        first_request_id,
        second_request_id,
    }
    assert agent_messages[0].group_id == agent_messages[1].group_id
    assert len(handoffs) == 2
    assert {event.idempotency_key for event in handoffs} == {
        f"agent_runtime:content_processing_handoff:{first_request_id}:v2",
        f"agent_runtime:content_processing_handoff:{second_request_id}:v2",
    }
    assert all(event.status == OutboxEventStatus.PUBLISHED for event in handoffs)
    assert all(event.status == OutboxEventStatus.PUBLISHED for event in download_events)
    assert len(gateway.calls) == 2
    assert len(telegram.calls) == 2
    assert len(content_processing.calls) == 2
    assert len({call["idempotency_key"] for call in content_processing.calls}) == 2


@pytest.mark.asyncio
async def test_download_handler_invalid_request_notifies_without_handoff(
    agent_runtime_uow_factory,
    agent_runtime_sync_uow_factory,
    agent_runtime_sync_sessionmaker: sessionmaker[Session],
) -> None:
    chat_id = 9307
    claim_token = await _ingest_coordinate_classify_download(
        agent_runtime_uow_factory,
        agent_runtime_sync_uow_factory,
        chat_id=chat_id,
        key="dl-invalid",
        messages=(
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=1,
                text=None,
                attachment=IngestAttachmentCommand(
                    ingress_attachment_id=uuid4(),
                    type=TelegramAttachmentType.VIDEO,
                    status="ready",
                    file_id="vid-invalid",
                ),
            ),
            IngestMessageCommand(
                ingress_message_id=uuid4(),
                telegram_user_id=1,
                message_id=2,
                text="what is the weather today?",
            ),
        ),
    )

    rejection = (
        "I only handle download-related requests for media "
        "(subtitles, language, prepare). Please send a download instruction."
    )
    gateway = FixedDownloadGateway(
        is_download_request=False,
        assistant_text=rejection,
        subtitle=None,
        dub=None,
    )
    telegram = RecordingTelegramClient()
    result = SyncDownloadHandlerService(
        uow_factory=agent_runtime_sync_uow_factory,
        llm_gateway_client=gateway,  # type: ignore[arg-type]
        telegram_ingress_client=telegram,  # type: ignore[arg-type]
        settings=_settings(),
    ).process_conversation(chat_id=chat_id, claim_token=claim_token)

    assert result.processed >= 1
    assert result.results[0].agent_message_id is None
    assert len(gateway.calls) == 1
    assert len(telegram.calls) == 1
    assert telegram.calls[0]["text"] == rejection

    with agent_runtime_sync_sessionmaker() as session:
        agent_messages = list(session.scalars(select(AgentMessage)).all())
        handoff = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type
                    == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value
                )
            ).all()
        )
        download_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == OutboxEventType.DOWNLOAD_HANDLER.value
                )
            ).all()
        )

    assert agent_messages == []
    assert handoff == []
    assert download_events
    assert all(e.status == OutboxEventStatus.PUBLISHED for e in download_events)


def test_download_agent_prompts_mention_is_download_request() -> None:
    from telegram_agent.core.agent_runtime.prompts.download_agent import (
        build_download_agent_prompts,
    )

    for media in (
        TelegramAttachmentType.VIDEO,
        TelegramAttachmentType.AUDIO,
        TelegramAttachmentType.DOCUMENT,
    ):
        prompts = build_download_agent_prompts(
            media_type=media,
            group_texts=["hello"],
            media_message_id=1,
        )
        assert "is_download_request" in prompts.system_prompt
        assert "false" in prompts.system_prompt.lower() or "False" in prompts.system_prompt
