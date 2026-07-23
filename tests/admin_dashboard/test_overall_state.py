from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard.common.types import OverallState
from telegram_agent.core.admin_dashboard.services.overall_state import derive_overall_state
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    AttachmentRow,
    ContentProcessingView,
    JobRow,
    RuntimeMessageRow,
    UserMessageRow,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _message(
    *,
    conversation_status: str = "pending",
    attachment: AttachmentRow | None = None,
) -> UserMessageRow:
    return UserMessageRow(
        id=uuid4(),
        telegram_user_id=1,
        chat_id=10,
        message_id=100,
        update_id=None,
        reply_message_id=None,
        text="hello",
        conversation_status=conversation_status,
        dispatch_event_id=None,
        created_at=_now(),
        attachment=attachment,
    )


def test_text_only_pending_dispatch() -> None:
    state = derive_overall_state(message=_message(), content=None, runtime=None)
    assert state == OverallState.PENDING_DISPATCH


def test_blocking_voice_waiting_media() -> None:
    att = AttachmentRow(
        id=uuid4(),
        user_message_id=uuid4(),
        file_id="f",
        file_unique_id=None,
        type="voice",
        status="processing",
        created_at=_now(),
    )
    state = derive_overall_state(
        message=_message(attachment=att),
        content=None,
        runtime=None,
    )
    assert state == OverallState.WAITING_MEDIA


def test_failed_attachment() -> None:
    att = AttachmentRow(
        id=uuid4(),
        user_message_id=uuid4(),
        file_id="f",
        file_unique_id=None,
        type="photo",
        status="failed",
        created_at=_now(),
    )
    state = derive_overall_state(
        message=_message(attachment=att),
        content=None,
        runtime=None,
    )
    assert state == OverallState.FAILED


def test_completed_after_coordination() -> None:
    msg = _message(conversation_status="dispatched")
    runtime_msg = RuntimeMessageRow(
        id=uuid4(),
        batch_id=uuid4(),
        ingress_message_id=msg.id,
        chat_id=msg.chat_id,
        telegram_user_id=msg.telegram_user_id,
        message_id=msg.message_id,
        reply_message_id=None,
        text="hello",
        attachment_ingress_id=None,
        attachment_type=None,
        attachment_status=None,
        attachment_file_id=None,
        attachment_file_unique_id=None,
        group_id=uuid4(),
        coordination_status="grouped",
        status="classified",
        intent="conversation",
        coordinated_at=_now(),
        created_at=_now(),
    )
    state = derive_overall_state(
        message=msg,
        content=None,
        runtime=AgentRuntimeView(
            message=runtime_msg,
            batch=None,
            group=None,
            outbox=None,
            claim=None,
        ),
    )
    assert state == OverallState.COMPLETED


def test_classifying_after_coordination() -> None:
    msg = _message(conversation_status="dispatched")
    runtime_msg = RuntimeMessageRow(
        id=uuid4(),
        batch_id=uuid4(),
        ingress_message_id=msg.id,
        chat_id=msg.chat_id,
        telegram_user_id=msg.telegram_user_id,
        message_id=msg.message_id,
        reply_message_id=None,
        text="hello",
        attachment_ingress_id=None,
        attachment_type=None,
        attachment_status=None,
        attachment_file_id=None,
        attachment_file_unique_id=None,
        group_id=uuid4(),
        coordination_status="grouped",
        status="coordinated",
        intent=None,
        coordinated_at=_now(),
        created_at=_now(),
    )
    state = derive_overall_state(
        message=msg,
        content=None,
        runtime=AgentRuntimeView(
            message=runtime_msg,
            batch=None,
            group=None,
            outbox=None,
            claim=None,
        ),
    )
    assert state == OverallState.CLASSIFYING


def test_processing_media_from_job_status() -> None:
    msg = _message(
        attachment=AttachmentRow(
            id=uuid4(),
            user_message_id=uuid4(),
            file_id="f",
            file_unique_id=None,
            type="photo",
            status="processing",
            created_at=_now(),
        )
    )
    content = ContentProcessingView(
        job=JobRow(
            id=uuid4(),
            kind="telegram attachment",
            status="running",
            idempotency_key="k",
            error_message=None,
            callback_required=True,
            created_at=_now(),
            updated_at=_now(),
        ),
        source=None,
    )
    state = derive_overall_state(message=msg, content=content, runtime=None)
    assert state == OverallState.PROCESSING_MEDIA


def test_processing_media_while_chunking() -> None:
    msg = _message(
        attachment=AttachmentRow(
            id=uuid4(),
            user_message_id=uuid4(),
            file_id="f",
            file_unique_id=None,
            type="voice",
            status="processing",
            created_at=_now(),
        )
    )
    for status in ("transcribed", "chunking"):
        content = ContentProcessingView(
            job=JobRow(
                id=uuid4(),
                kind="telegram attachment",
                status=status,
                idempotency_key=f"k-{status}",
                error_message=None,
                callback_required=True,
                created_at=_now(),
                updated_at=_now(),
            ),
            source=None,
        )
        state = derive_overall_state(message=msg, content=content, runtime=None)
        assert state == OverallState.PROCESSING_MEDIA, status
