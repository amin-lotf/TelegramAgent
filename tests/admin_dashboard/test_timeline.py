from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard.common.types import StageKey, StageStatus
from telegram_agent.core.admin_dashboard.services.timeline import build_timeline
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentMessageRow,
    AgentRuntimeView,
    AttachmentRow,
    ChunkEmbeddingRow,
    ContentChunkRow,
    ContentProcessingView,
    JobRow,
    MediaAssetRow,
    OutboxRow,
    RuntimeMessageRow,
    TelegramSourceRow,
    TranscriptRow,
    TranscriptSegmentRow,
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
            status="chunked",
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
        chunks=(
            ContentChunkRow(
                id=uuid4(),
                job_id=job_id,
                content_type="transcript",
                chunk_index=0,
                text="transcript",
                start_ms=0,
                end_ms=1000,
                char_count=10,
                token_count=2,
                segment_index_start=0,
                segment_index_end=0,
                speakers=None,
                strategy="transcript_segment_window_v1",
                created_at=now,
            ),
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
    assert by_key[StageKey.CHUNKING_DONE].status == StageStatus.COMPLETED
    assert "1 chunk" in (by_key[StageKey.CHUNKING_DONE].detail or "")
    # Historical chunks without vectors → embedding skipped in the active pipeline.
    assert by_key[StageKey.EMBEDDING_DONE].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED
    assert by_key[StageKey.COORDINATED].status == StageStatus.COMPLETED


def test_embedding_completed_when_vectors_present() -> None:
    message_id = uuid4()
    att_id = uuid4()
    job_id = uuid4()
    chunk_id = uuid4()
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
            status="ready",
            created_at=now,
        ),
    )
    content = ContentProcessingView(
        job=JobRow(
            id=job_id,
            kind="telegram attachment",
            status="embedded",
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
        chunks=(
            ContentChunkRow(
                id=chunk_id,
                job_id=job_id,
                content_type="transcript",
                chunk_index=0,
                text="hello",
                start_ms=0,
                end_ms=500,
                char_count=5,
                token_count=1,
                segment_index_start=0,
                segment_index_end=0,
                speakers=None,
                strategy="transcript_segment_window_v1",
                created_at=now,
            ),
        ),
        embeddings=(
            ChunkEmbeddingRow(
                id=uuid4(),
                job_id=job_id,
                chunk_id=chunk_id,
                chunk_index=0,
                provider="openai",
                model="text-embedding-3-small",
                dimensions=1536,
                embedding_preview=(0.01, -0.02, 0.03, 0.04),
                created_at=now,
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
    by_key = {e.key: e for e in events}
    assert by_key[StageKey.CHUNKING_DONE].status == StageStatus.COMPLETED
    assert by_key[StageKey.EMBEDDING_DONE].status == StageStatus.COMPLETED
    assert "1 embedding" in (by_key[StageKey.EMBEDDING_DONE].detail or "")
    assert "text-embedding-3-small" in (by_key[StageKey.EMBEDDING_DONE].detail or "")
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED


def test_legacy_transcribed_without_emotion_stage() -> None:
    """Jobs that finished at transcribed before emotion extraction still complete CP."""
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
        chunks=(),
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
    assert by_key[StageKey.EMOTION_EXTRACTION_DONE].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.CHUNKING_DONE].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.EMBEDDING_DONE].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED


def test_emotion_extraction_happy_path() -> None:
    message_id = uuid4()
    att_id = uuid4()
    job_id = uuid4()
    transcript_id = uuid4()
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
            status="ready",
            created_at=now,
        ),
    )
    content = ContentProcessingView(
        job=JobRow(
            id=job_id,
            kind="telegram attachment",
            status="emotion_extracted",
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
        outbox_events=(
            OutboxRow(
                id=uuid4(),
                event_type="content_processing.transcript.ready_for_emotion_extraction",
                status="published",
                attempt_count=1,
                created_at=now,
                published_at=now,
                available_at=now,
                locked_at=None,
                locked_by=None,
                last_error=None,
                idempotency_key=f"emotion:{job_id}",
                payload={},
                job_id=job_id,
            ),
            OutboxRow(
                id=uuid4(),
                event_type="content_processing.job.finished",
                status="published",
                attempt_count=1,
                created_at=now,
                published_at=now,
                available_at=now,
                locked_at=None,
                locked_by=None,
                last_error=None,
                idempotency_key=f"finished:{job_id}",
                payload={},
                job_id=job_id,
            ),
        ),
        transcript=TranscriptRow(
            id=transcript_id,
            job_id=job_id,
            text="hello",
            language="en",
            language_probability=0.9,
            duration_ms=500,
            segments=(
                TranscriptSegmentRow(
                    id=uuid4(),
                    transcript_id=transcript_id,
                    segment_index=0,
                    start_ms=0,
                    end_ms=500,
                    text="hello",
                    language="en",
                    language_probability=0.9,
                    speaker=None,
                    speaker_confidence=None,
                    emotion="HAPPY",
                    audio_events=("Speech",),
                ),
            ),
        ),
        chunks=(),
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
    assert by_key[StageKey.EMOTION_EXTRACTION_DONE].status == StageStatus.COMPLETED
    assert "1/1 segment emotion" in (by_key[StageKey.EMOTION_EXTRACTION_DONE].detail or "")
    assert by_key[StageKey.CHUNKING_DONE].status == StageStatus.NOT_APPLICABLE
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.COMPLETED


def test_emotion_extraction_pending_after_transcription() -> None:
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
        outbox_events=(
            OutboxRow(
                id=uuid4(),
                event_type="content_processing.transcript.ready_for_emotion_extraction",
                status="pending",
                attempt_count=0,
                created_at=now,
                published_at=None,
                available_at=now,
                locked_at=None,
                locked_by=None,
                last_error=None,
                idempotency_key=f"emotion:{job_id}",
                payload={},
                job_id=job_id,
            ),
        ),
        transcript=TranscriptRow(
            id=uuid4(),
            job_id=job_id,
            text="hello",
            language="en",
            language_probability=0.9,
            duration_ms=500,
        ),
        chunks=(),
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
    assert by_key[StageKey.EMOTION_EXTRACTION_DONE].status == StageStatus.PENDING
    assert by_key[StageKey.CP_FINISHED].status == StageStatus.PENDING
