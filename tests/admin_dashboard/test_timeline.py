from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard.common.types import StageKey, StageStatus
from telegram_agent.core.admin_dashboard.services.timeline import build_timeline
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentMessageRow,
    AgentRuntimeView,
    AttachmentRow,
    ContentProcessingView,
    DownloadRequestView,
    DubbingWorkflowRow,
    JobRow,
    MediaAssetRow,
    OutboxRow,
    RuntimeMessageRow,
    TelegramSourceRow,
    TranscriptRow,
    UserMessageRow,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_text_only_timeline_marks_cp_not_applicable() -> None:
    message = UserMessageRow(
        id=uuid4(),
        telegram_user_id=1,
        chat_id=1,
        message_id=1,
        update_id=None,
        reply_message_id=None,
        text="hi",
        conversation_status="pending",
        dispatch_event_id=None,
        created_at=_now(),
    )
    events = build_timeline(
        message=message,
        ingress_outbox=None,
        content=None,
        runtime=None,
        cp_available=True,
        runtime_available=True,
    )
    by_key = {e.key: e for e in events}
    assert by_key[StageKey.MESSAGE_RECEIVED].status == StageStatus.COMPLETED
    assert by_key[StageKey.ATTACHMENT_REGISTERED].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.CP_JOB_CREATED].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.RUNTIME_INGESTED].status == StageStatus.NOT_STARTED
    assert by_key[StageKey.DUBBING].status == StageStatus.NOT_APPLICABLE


def test_download_timeline_uses_agent_result_for_traced_request() -> None:
    request_id = uuid4()
    stale_request_id = uuid4()
    group_id = uuid4()
    now = _now()
    stale_created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    message = UserMessageRow(
        id=request_id,
        telegram_user_id=1,
        chat_id=1,
        message_id=2,
        update_id=None,
        reply_message_id=None,
        text="english subtitles",
        conversation_status="dispatched",
        dispatch_event_id=uuid4(),
        created_at=now,
    )
    runtime = AgentRuntimeView(
        message=RuntimeMessageRow(
            id=uuid4(),
            batch_id=uuid4(),
            ingress_message_id=request_id,
            chat_id=1,
            telegram_user_id=1,
            message_id=2,
            reply_message_id=None,
            text="english subtitles",
            attachment_ingress_id=None,
            attachment_type=None,
            attachment_status=None,
            attachment_file_id=None,
            attachment_file_unique_id=None,
            group_id=group_id,
            coordination_status="grouped",
            status="coordinated",
            intent=None,
            coordinated_at=now,
            created_at=now,
        ),
        batch=None,
        group=None,
        outbox=None,
        claim=None,
        agent_messages=(
            AgentMessageRow(
                id=uuid4(),
                ingress_message_id=stale_request_id,
                chat_id=1,
                telegram_user_id=1,
                group_id=group_id,
                text="stale response",
                role="download_agent",
                created_at=stale_created_at,
            ),
            AgentMessageRow(
                id=uuid4(),
                ingress_message_id=request_id,
                chat_id=1,
                telegram_user_id=1,
                group_id=group_id,
                text="matching response",
                role="download_agent",
                created_at=now,
            ),
        ),
    )

    events = build_timeline(
        message=message,
        ingress_outbox=None,
        content=None,
        runtime=runtime,
        cp_available=True,
        runtime_available=True,
    )

    download = next(event for event in events if event.key == StageKey.DOWNLOAD_HANDLED)
    assert download.status == StageStatus.COMPLETED
    assert download.timestamp == now


def test_voice_happy_path_timeline() -> None:
    message_id = uuid4()
    att_id = uuid4()
    job_id = uuid4()
    now = _now()
    message = UserMessageRow(
        id=message_id,
        telegram_user_id=1,
        chat_id=1,
        message_id=5,
        update_id=None,
        reply_message_id=None,
        text="transcript",
        conversation_status="dispatched",
        dispatch_event_id=uuid4(),
        created_at=now,
        attachment=AttachmentRow(
            id=att_id,
            user_message_id=message_id,
            file_id="file",
            file_unique_id=None,
            type="voice",
            status="ready",
            created_at=now,
        ),
    )
    content = ContentProcessingView(
        job=JobRow(
            id=job_id,
            kind="telegram attachment",
            status="transcribed",
            idempotency_key="k",
            error_message=None,
            callback_required=True,
            created_at=now,
            updated_at=now,
        ),
        source=TelegramSourceRow(
            id=uuid4(),
            job_id=job_id,
            ingress_message_id=message_id,
            ingress_attachment_id=att_id,
            telegram_user_id=1,
            telegram_file_id="file",
            telegram_file_unique_id=None,
            attachment_type="voice",
        ),
        assets=(
            MediaAssetRow(
                id=uuid4(),
                job_id=job_id,
                role="source",
                parent_asset_id=None,
                local_path="/app/media/x.ogg",
                media_type="voice",
                mime_type="audio/ogg",
                duration_ms=1000,
                size_bytes=10,
            ),
        ),
        outbox_events=(),
        transcript=TranscriptRow(
            id=uuid4(),
            job_id=job_id,
            text="transcript",
            language="en",
            language_probability=0.9,
            duration_ms=1000,
        ),
    )
    runtime = AgentRuntimeView(
        message=RuntimeMessageRow(
            id=uuid4(),
            batch_id=uuid4(),
            ingress_message_id=message_id,
            chat_id=1,
            telegram_user_id=1,
            message_id=5,
            reply_message_id=None,
            text="transcript",
            attachment_ingress_id=att_id,
            attachment_type="voice",
            attachment_status="ready",
            attachment_file_id="file",
            attachment_file_unique_id=None,
            group_id=uuid4(),
            coordination_status="grouped",
            status="coordinated",
            intent=None,
            coordinated_at=now,
            created_at=now,
        ),
        batch=None,
        group=None,
        outbox=None,
        claim=None,
    )
    events = build_timeline(
        message=message,
        ingress_outbox=None,
        content=content,
        runtime=runtime,
        cp_available=True,
        runtime_available=True,
    )
    by_key = {e.key: e for e in events}
    assert by_key[StageKey.TRANSCRIPTION_DONE].status == StageStatus.COMPLETED
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED
    assert by_key[StageKey.COORDINATED].status == StageStatus.COMPLETED


def test_transcribed_job_completes_content_processing() -> None:
    """Transcription is the terminal content-processing media stage."""
    message_id = uuid4()
    att_id = uuid4()
    job_id = uuid4()
    now = _now()
    message = UserMessageRow(
        id=message_id,
        telegram_user_id=1,
        chat_id=1,
        message_id=5,
        update_id=None,
        reply_message_id=None,
        text=None,
        conversation_status="pending",
        dispatch_event_id=None,
        created_at=now,
        attachment=AttachmentRow(
            id=att_id,
            user_message_id=message_id,
            file_id="file",
            file_unique_id=None,
            type="voice",
            status="processing",
            created_at=now,
        ),
    )
    content = ContentProcessingView(
        job=JobRow(
            id=job_id,
            kind="telegram attachment",
            status="transcribed",
            idempotency_key="k",
            error_message=None,
            callback_required=True,
            created_at=now,
            updated_at=now,
        ),
        source=TelegramSourceRow(
            id=uuid4(),
            job_id=job_id,
            ingress_message_id=message_id,
            ingress_attachment_id=att_id,
            telegram_user_id=1,
            telegram_file_id="file",
            telegram_file_unique_id=None,
            attachment_type="voice",
        ),
        assets=(),
        outbox_events=(),
        transcript=TranscriptRow(
            id=uuid4(),
            job_id=job_id,
            text="hello",
            language="en",
            language_probability=0.9,
            duration_ms=500,
        ),
    )
    events = build_timeline(
        message=message,
        ingress_outbox=None,
        content=content,
        runtime=None,
        cp_available=True,
        runtime_available=True,
    )
    by_key = {e.key: e for e in events}
    assert by_key[StageKey.TRANSCRIPTION_DONE].status == StageStatus.COMPLETED
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED
    assert by_key[StageKey.DUBBING].status == StageStatus.NOT_APPLICABLE


def test_dubbing_timeline_shows_sam_running_stage() -> None:
    now = _now()
    gpu_job_id = uuid4()
    message = UserMessageRow(
        id=uuid4(),
        telegram_user_id=1,
        chat_id=1,
        message_id=9,
        update_id=None,
        reply_message_id=None,
        text="persian dub",
        conversation_status="dispatched",
        dispatch_event_id=uuid4(),
        created_at=now,
    )
    content = ContentProcessingView(
        job=None,
        source=None,
        download_requests=(
            DownloadRequestView(
                id=uuid4(),
                job_id=uuid4(),
                media_ingress_message_id=message.id,
                media_type="video",
                requested_subtitle_language=None,
                requested_dub_language="persian",
                delivery_status="pending",
                delivery_error=None,
                assistant_text="Preparing the video with Persian dub.",
                created_at=now,
                updated_at=now,
                dubbing=DubbingWorkflowRow(
                    id=uuid4(),
                    job_id=uuid4(),
                    source_job_id=uuid4(),
                    target_language="persian",
                    status="sam_running",
                    status_label="Separating original audio (SAM Audio)",
                    active_gpu_job_id=gpu_job_id,
                    cosyvoice_model="Fun-CosyVoice3-0.5B",
                    sam_model="facebook/sam-audio-small",
                    error_message=None,
                    created_at=now,
                    updated_at=now,
                ),
            ),
        ),
    )
    events = build_timeline(
        message=message,
        ingress_outbox=None,
        content=content,
        runtime=None,
        cp_available=True,
        runtime_available=True,
    )
    event = {item.key: item for item in events}[StageKey.DUBBING]
    assert event.status == StageStatus.PENDING
    assert event.detail is not None
    assert "Separating original audio (SAM Audio)" in event.detail
    assert str(gpu_job_id) in event.detail
