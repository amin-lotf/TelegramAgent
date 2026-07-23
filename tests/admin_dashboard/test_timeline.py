from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard.common.types import StageKey, StageStatus
from telegram_agent.core.admin_dashboard.services.timeline import build_timeline
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    AttachmentRow,
    ContentProcessingView,
    JobRow,
    MediaAssetRow,
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


def test_voice_happy_path_timeline() -> None:
    message_id = uuid4()
    att_id = uuid4()
    job_id = uuid4()
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
        created_at=_now(),
        attachment=AttachmentRow(
            id=att_id,
            user_message_id=message_id,
            file_id="file",
            file_unique_id=None,
            type="voice",
            status="ready",
            created_at=_now(),
        ),
    )
    content = ContentProcessingView(
        job=JobRow(
            id=job_id,
            kind="telegram attachment",
            status="completed",
            idempotency_key="k",
            error_message=None,
            callback_required=True,
            created_at=_now(),
            updated_at=_now(),
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
            status="classified",
            intent="conversation",
            coordinated_at=_now(),
            created_at=_now(),
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
    assert by_key[StageKey.COORDINATED].status == StageStatus.COMPLETED
