from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, uuid4

from telegram_agent.core.admin_dashboard.common.types import StageStatus, WorkflowState
from telegram_agent.core.admin_dashboard.services.message_trace import (
    classify_download_requests,
)
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    ContentProcessingView,
    DownloadRequestView,
    DubbingWorkflowRow,
    JobRow,
    OutboxRow,
    RuntimeMessageRow,
    SubtitleTranslationRow,
    TranslationBatchRow,
    UserMessageRow,
)
from telegram_agent.core.admin_dashboard.services.workflows import (
    build_download_workflow,
    build_workflow_collection,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _message(*, message_id: int = 12) -> UserMessageRow:
    return UserMessageRow(
        id=uuid4(),
        telegram_user_id=1,
        chat_id=10,
        message_id=message_id,
        update_id=None,
        reply_message_id=None,
        text="create subtitles",
        conversation_status="dispatched",
        dispatch_event_id=uuid4(),
        created_at=_now(),
    )


def _job(*, status: str = "running", error: str | None = None) -> JobRow:
    now = _now()
    return JobRow(
        id=uuid4(),
        kind="download preparation",
        status=status,
        idempotency_key=str(uuid4()),
        error_message=error,
        callback_required=False,
        created_at=now,
        updated_at=now,
    )


def _request(
    *,
    media_ingress_message_id: UUID | None = None,
    agent_message_id: UUID | None = None,
    creator_ingress_message_id: UUID | None = None,
    reply_to_message_id: int | None = 12,
    job: JobRow | None = None,
) -> DownloadRequestView:
    now = _now()
    resolved_job = job or _job()
    return DownloadRequestView(
        id=uuid4(),
        job_id=resolved_job.id,
        media_ingress_message_id=media_ingress_message_id or uuid4(),
        media_type="video",
        requested_subtitle_language="fa",
        requested_dub_language=None,
        delivery_status="pending",
        delivery_error=None,
        assistant_text="Preparing Persian subtitles",
        created_at=now,
        updated_at=now,
        agent_message_id=agent_message_id,
        creator_ingress_message_id=creator_ingress_message_id,
        reply_to_message_id=reply_to_message_id,
        job=resolved_job,
        source_job=_job(status="transcribed"),
        source_transcript_language="en",
    )


def test_creator_correlation_wins_over_source_relationship() -> None:
    message = _message()
    agent_id = uuid4()
    owned = _request(agent_message_id=agent_id, creator_ingress_message_id=message.id)
    dependent = _request(
        media_ingress_message_id=message.id,
        agent_message_id=uuid4(),
        creator_ingress_message_id=uuid4(),
        reply_to_message_id=99,
    )

    direct, related = classify_download_requests(
        message=message,
        candidates=[owned, dependent],
        direct_agent_ids=(agent_id,),
    )

    assert direct == (owned,)
    assert related == (dependent,)


def test_reply_id_is_only_a_compatibility_fallback() -> None:
    message = _message()
    fallback = _request(creator_ingress_message_id=None)
    known_other_creator = _request(
        creator_ingress_message_id=uuid4(),
        reply_to_message_id=message.message_id,
    )

    direct, related = classify_download_requests(
        message=message,
        candidates=[fallback, known_other_creator],
        direct_agent_ids=(),
    )

    assert direct == (fallback,)
    assert related == ()


def test_source_message_exposes_dependency_without_owning_it() -> None:
    message = _message()
    creator_id = uuid4()
    dependent = _request(
        media_ingress_message_id=message.id,
        creator_ingress_message_id=creator_id,
        reply_to_message_id=99,
    )
    collection = build_workflow_collection(
        message=message,
        content=ContentProcessingView(
            job=None,
            source=None,
            related_download_requests=(dependent,),
        ),
        runtime=None,
        cp_available=True,
    )

    assert collection.items == ()
    assert len(collection.related) == 1
    assert collection.related[0].creator_ingress_message_id == creator_id
    assert collection.polling_needed


def test_dubbing_workflow_reports_sam_as_current_stage() -> None:
    now = _now()
    job = _job()
    request = _request(job=job)
    assert request.source_job is not None
    request = replace(
        request,
        requested_subtitle_language=None,
        requested_dub_language="fa",
        dubbing=DubbingWorkflowRow(
                id=uuid4(),
                job_id=job.id,
                source_job_id=request.source_job.id,
                target_language="fa",
                status="sam_running",
                status_label="Separating original audio (SAM Audio)",
                active_gpu_job_id=uuid4(),
                cosyvoice_model="CosyVoice",
                sam_model="SAM Audio",
                error_message=None,
                created_at=now,
                updated_at=now,
        ),
    )

    workflow = build_download_workflow(request)
    by_key = {stage.key: stage for stage in workflow.stages}

    assert workflow.state == WorkflowState.RUNNING
    assert workflow.current_stage == "Separate background with SAM Audio"
    assert by_key["cosyvoice"].status == StageStatus.COMPLETED
    assert by_key["sam"].status == StageStatus.PENDING
    assert by_key["sam"].detail is not None
    assert "GPU job" in by_key["sam"].detail


def test_subtitle_workflow_reports_translation_batch_progress() -> None:
    now = _now()
    request = _request()
    translation = SubtitleTranslationRow(
        id=uuid4(),
        job_id=request.source_job.id,
        source_language="en",
        target_language="fa",
        status="translating",
        model_name="madlad",
        error_message=None,
        created_at=now,
        updated_at=now,
        completed_at=None,
        batches=(
            TranslationBatchRow(
                id=uuid4(),
                batch_index=0,
                start_segment_index=0,
                end_segment_index=9,
                status="succeeded",
                attempt_count=1,
                last_error=None,
                created_at=now,
                updated_at=now,
            ),
            TranslationBatchRow(
                id=uuid4(),
                batch_index=1,
                start_segment_index=10,
                end_segment_index=19,
                status="processing",
                attempt_count=1,
                last_error=None,
                created_at=now,
                updated_at=now,
            ),
        ),
    )
    request = replace(request, translation=translation)

    workflow = build_download_workflow(request)
    translation_stage = next(
        stage for stage in workflow.stages if stage.key == "translation"
    )

    assert workflow.current_stage == "Translate transcript"
    assert translation_stage.status == StageStatus.PENDING
    assert translation_stage.detail is not None
    assert "1/2 batches" in translation_stage.detail


def test_pending_handoff_creates_provisional_workflow() -> None:
    message = _message()
    now = _now()
    runtime_message = RuntimeMessageRow(
        id=uuid4(),
        batch_id=uuid4(),
        ingress_message_id=message.id,
        chat_id=message.chat_id,
        telegram_user_id=message.telegram_user_id,
        message_id=message.message_id,
        reply_message_id=None,
        text=message.text,
        attachment_ingress_id=None,
        attachment_type=None,
        attachment_status=None,
        attachment_file_id=None,
        attachment_file_unique_id=None,
        group_id=uuid4(),
        coordination_status="grouped",
        status="coordinated",
        intent=None,
        coordinated_at=now,
        created_at=now,
    )
    event = OutboxRow(
        id=uuid4(),
        event_type="agent_runtime.message.content_processing_handoff",
        status="pending",
        attempt_count=0,
        created_at=now,
        published_at=None,
        available_at=now,
        locked_at=None,
        locked_by=None,
        last_error=None,
        idempotency_key="handoff",
        payload={},
    )
    runtime = AgentRuntimeView(
        message=runtime_message,
        batch=None,
        group=None,
        outbox=event,
        claim=None,
        outbox_events=(event,),
    )

    collection = build_workflow_collection(
        message=message,
        content=ContentProcessingView(job=None, source=None),
        runtime=runtime,
        cp_available=True,
    )

    assert collection.count == 1
    assert collection.items[0].kind == "workflow_handoff"
    assert collection.items[0].state == WorkflowState.PENDING
    assert collection.polling_needed


def test_delivered_subtitle_workflow_is_completed() -> None:
    now = _now()
    request = _request(job=_job(status="completed"))
    request = replace(
        request,
        requested_subtitle_language="en",
        final_path_exists=True,
        delivery_status="delivered",
        delivered_at=now,
    )

    workflow = build_download_workflow(request)

    assert workflow.state == WorkflowState.COMPLETED
    assert workflow.current_stage == "Delivered to Telegram"


def test_translation_failure_is_workflow_failure() -> None:
    now = _now()
    request = _request()
    assert request.source_job is not None
    request = replace(
        request,
        translation=SubtitleTranslationRow(
            id=uuid4(),
            job_id=request.source_job.id,
            source_language="en",
            target_language="fa",
            status="failed",
            model_name=None,
            error_message="provider rejected batch",
            created_at=now,
            updated_at=now,
            completed_at=None,
        ),
    )

    workflow = build_download_workflow(request)

    assert workflow.state == WorkflowState.FAILED
    assert workflow.current_stage == "Translate transcript"
    assert workflow.error_message == "provider rejected batch"


def test_unknown_dubbing_status_is_visible_as_unavailable() -> None:
    now = _now()
    request = _request()
    assert request.source_job is not None
    request = replace(
        request,
        requested_subtitle_language=None,
        requested_dub_language="fa",
        dubbing=DubbingWorkflowRow(
            id=uuid4(),
            job_id=request.job_id,
            source_job_id=request.source_job.id,
            target_language="fa",
            status="future_stage",
            status_label="future stage",
            active_gpu_job_id=None,
            cosyvoice_model="CosyVoice",
            sam_model="SAM Audio",
            error_message=None,
            created_at=now,
            updated_at=now,
        ),
    )

    workflow = build_download_workflow(request)

    assert workflow.state == WorkflowState.UNAVAILABLE
    assert all(stage.status == StageStatus.UNAVAILABLE for stage in workflow.stages[2:6])


def test_cancelled_dubbing_workflow_is_terminal() -> None:
    now = _now()
    job = _job(status="cancelled")
    request = _request(job=job)
    assert request.source_job is not None
    request = replace(
        request,
        requested_subtitle_language=None,
        requested_dub_language="fa",
        dubbing=DubbingWorkflowRow(
            id=uuid4(),
            job_id=job.id,
            source_job_id=request.source_job.id,
            target_language="fa",
            status="cancelled",
            status_label="Cancelled",
            active_gpu_job_id=None,
            cosyvoice_model="CosyVoice",
            sam_model="SAM Audio",
            error_message=None,
            created_at=now,
            updated_at=now,
        ),
    )

    workflow = build_download_workflow(request)

    assert workflow.state == WorkflowState.CANCELLED
    assert any(stage.status == StageStatus.CANCELLED for stage in workflow.stages)


def test_cancelling_subtitle_job_is_not_reported_as_unknown() -> None:
    request = replace(
        _request(job=_job(status="cancelling")),
        delivery_status="cancelled",
    )

    workflow = build_download_workflow(request)

    assert workflow.state == WorkflowState.CANCELLED
