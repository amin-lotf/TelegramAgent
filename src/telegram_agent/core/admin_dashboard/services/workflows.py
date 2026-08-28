"""Project authoritative service records into operator-facing workflow stages."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from telegram_agent.core.admin_dashboard.common.types import (
    StageStatus,
    WorkflowState,
)
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    ContentProcessingView,
    DownloadRequestView,
    OutboxRow,
    RelatedWorkflowView,
    UserMessageRow,
    WorkflowCollection,
    WorkflowStageView,
    WorkflowView,
)
from telegram_agent.core.content_processing.common.language_codes import (
    InvalidLanguageCodeError,
    canonical_madlad_language,
)

_ACTIVE_JOBS = frozenset({"queued", "running", "downloaded", "transcribing"})
_SUCCESS_JOBS = frozenset({"transcribed", "completed"})
_FAILED_JOBS = frozenset({"failed", "timed_out"})
_KNOWN_JOBS = _ACTIVE_JOBS | _SUCCESS_JOBS | _FAILED_JOBS | {"cancelled"}

_DUBBING_ORDER = {
    "source_ready": 0,
    "preparing_inputs": 1,
    "tts_ready": 2,
    "tts_running": 3,
    "sam_ready": 4,
    "sam_running": 5,
    "assembly_ready": 6,
    "assembling": 7,
    "ready_for_delivery": 8,
}
_TERMINAL_WORKFLOWS = frozenset(
    {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}
)


def workflow_state_label(state: WorkflowState) -> str:
    return {
        WorkflowState.PENDING: "Pending",
        WorkflowState.RUNNING: "Running",
        WorkflowState.COMPLETED: "Completed",
        WorkflowState.FAILED: "Failed",
        WorkflowState.CANCELLED: "Cancelled",
        WorkflowState.UNAVAILABLE: "Unavailable",
    }[state]


def _stage(
    key: str,
    label: str,
    status: StageStatus,
    *,
    timestamp: datetime | None = None,
    detail: str | None = None,
) -> WorkflowStageView:
    return WorkflowStageView(
        key=key,
        label=label,
        status=status,
        timestamp=timestamp,
        detail=detail,
    )


def _current_stage(stages: tuple[WorkflowStageView, ...]) -> str:
    for status in (StageStatus.FAILED, StageStatus.CANCELLED, StageStatus.PENDING):
        for item in stages:
            if item.status == status:
                return item.label
    for item in stages:
        if item.status == StageStatus.NOT_STARTED:
            return item.label
    completed = [item for item in stages if item.status == StageStatus.COMPLETED]
    return completed[-1].label if completed else "Status unavailable"


def _latest_timestamp(stages: tuple[WorkflowStageView, ...]) -> datetime | None:
    values = [item.timestamp for item in stages if item.timestamp is not None]
    return max(values) if values else None


def _outbox(
    events: tuple[OutboxRow, ...],
    event_type: str,
) -> OutboxRow | None:
    return next((event for event in events if event.event_type == event_type), None)


def _event_time(event: OutboxRow | None) -> datetime | None:
    if event is None:
        return None
    return event.published_at or event.created_at


def _languages_match(source: str | None, target: str | None) -> bool:
    if not source or not target:
        return False
    if source.strip().casefold() == target.strip().casefold():
        return True
    try:
        return canonical_madlad_language(source) == canonical_madlad_language(target)
    except InvalidLanguageCodeError:
        return False


def _request_title(request: DownloadRequestView) -> tuple[str, str]:
    if request.requested_dub_language:
        language = request.requested_dub_language
        if request.requested_subtitle_language:
            return "video_dubbing", f"Dub + subtitles · {language}"
        return "video_dubbing", f"Video dubbing · {language}"
    if request.requested_subtitle_language:
        return (
            "video_subtitles",
            f"Video subtitles · {request.requested_subtitle_language}",
        )
    if request.media_type == "audio":
        suffix = f" · {request.requested_language}" if request.requested_language else ""
        return "audio_download", f"Audio preparation{suffix}"
    if request.media_type == "document":
        suffix = f" · {request.requested_format}" if request.requested_format else ""
        return "document_download", f"Document preparation{suffix}"
    return "video_download", "Video preparation"


def _source_stage(request: DownloadRequestView) -> WorkflowStageView:
    source = request.source_job
    if source is None:
        return _stage(
            "source_ready",
            "Source media ready",
            StageStatus.PENDING,
            detail="Waiting for the source media job",
        )
    if source.status in _FAILED_JOBS:
        return _stage(
            "source_ready",
            "Source media ready",
            StageStatus.FAILED,
            timestamp=source.updated_at,
            detail=source.error_message or source.status,
        )
    if source.status == "cancelled":
        return _stage(
            "source_ready",
            "Source media ready",
            StageStatus.CANCELLED,
            timestamp=source.updated_at,
            detail="Source processing was cancelled",
        )
    if source.status in _SUCCESS_JOBS:
        return _stage(
            "source_ready",
            "Source media ready",
            StageStatus.COMPLETED,
            timestamp=source.updated_at,
            detail=source.status,
        )
    if source.status in _ACTIVE_JOBS:
        return _stage(
            "source_ready",
            "Source media ready",
            StageStatus.PENDING,
            timestamp=source.updated_at,
            detail=source.status,
        )
    return _stage(
        "source_ready",
        "Source media ready",
        StageStatus.UNAVAILABLE,
        timestamp=source.updated_at,
        detail=f"Unknown source job status: {source.status}",
    )


def _delivery_stage(request: DownloadRequestView) -> WorkflowStageView:
    status = request.delivery_status
    if status == "delivered":
        return _stage(
            "delivery",
            "Delivered to Telegram",
            StageStatus.COMPLETED,
            timestamp=request.delivered_at or request.updated_at,
            detail=f"attempts={request.delivery_attempt_count}",
        )
    if status == "failed":
        return _stage(
            "delivery",
            "Delivered to Telegram",
            StageStatus.FAILED,
            timestamp=request.updated_at,
            detail=request.delivery_error or "Delivery failed",
        )
    if status in {"pending", "sending"}:
        return _stage(
            "delivery",
            "Delivered to Telegram",
            StageStatus.PENDING if request.final_path_exists else StageStatus.NOT_STARTED,
            timestamp=request.updated_at if status == "sending" else None,
            detail=status,
        )
    return _stage(
        "delivery",
        "Delivered to Telegram",
        StageStatus.UNAVAILABLE,
        timestamp=request.updated_at,
        detail=f"Unknown delivery status: {status}",
    )


def _translation_stage(request: DownloadRequestView) -> WorkflowStageView:
    target = request.requested_dub_language or request.requested_subtitle_language
    translation = request.translation
    if target is None or _languages_match(request.source_transcript_language, target):
        return _stage(
            "translation",
            "Translate transcript",
            StageStatus.NOT_APPLICABLE,
            detail="Source and target language match or translation was not requested",
        )
    if translation is None:
        source_ready = request.source_job is not None and request.source_job.status in _SUCCESS_JOBS
        return _stage(
            "translation",
            "Translate transcript",
            StageStatus.PENDING if source_ready else StageStatus.NOT_STARTED,
            detail=f"target={target}",
        )
    batches = translation.batches
    succeeded = sum(batch.status == "succeeded" for batch in batches)
    progress = f"{succeeded}/{len(batches)} batches" if batches else None
    failed_batch = next((batch for batch in batches if batch.status == "failed"), None)
    detail_parts = [part for part in (progress, translation.model_name) if part]
    if translation.status == "completed":
        return _stage(
            "translation",
            "Translate transcript",
            StageStatus.COMPLETED,
            timestamp=translation.completed_at or translation.updated_at,
            detail=" · ".join(detail_parts) or None,
        )
    if translation.status == "failed" or failed_batch is not None:
        error = translation.error_message or (
            failed_batch.last_error if failed_batch is not None else None
        )
        return _stage(
            "translation",
            "Translate transcript",
            StageStatus.FAILED,
            timestamp=translation.updated_at,
            detail=error or "Translation failed",
        )
    if translation.status in {"pending", "building_glossary", "translating"}:
        detail_parts.insert(0, translation.status.replace("_", " "))
        return _stage(
            "translation",
            "Translate transcript",
            StageStatus.PENDING,
            timestamp=translation.updated_at,
            detail=" · ".join(detail_parts),
        )
    return _stage(
        "translation",
        "Translate transcript",
        StageStatus.UNAVAILABLE,
        timestamp=translation.updated_at,
        detail=f"Unknown translation status: {translation.status}",
    )


def _workflow_state(
    request: DownloadRequestView,
    stages: tuple[WorkflowStageView, ...],
) -> WorkflowState:
    job_status = request.job.status if request.job is not None else None
    dubbing_status = request.dubbing.status if request.dubbing is not None else None
    if (
        job_status == "cancelled"
        or dubbing_status in {"cancelling", "cancelled"}
        or any(item.status == StageStatus.CANCELLED for item in stages)
    ):
        return WorkflowState.CANCELLED
    if any(item.status == StageStatus.FAILED for item in stages):
        return WorkflowState.FAILED
    if job_status is not None and job_status not in _KNOWN_JOBS:
        return WorkflowState.UNAVAILABLE
    if any(item.status == StageStatus.UNAVAILABLE for item in stages):
        return WorkflowState.UNAVAILABLE
    if request.delivery_status == "delivered":
        return WorkflowState.COMPLETED
    if request.job is None or request.job.status == "queued":
        return WorkflowState.PENDING
    return WorkflowState.RUNNING


def build_download_workflow(request: DownloadRequestView) -> WorkflowView:
    kind, title = _request_title(request)
    accepted = _stage(
        "accepted",
        "Content-processing job accepted",
        StageStatus.COMPLETED if request.job is not None else StageStatus.PENDING,
        timestamp=request.job.created_at if request.job is not None else request.created_at,
        detail=request.job.status if request.job is not None else "Awaiting job record",
    )
    source = _source_stage(request)
    stages: list[WorkflowStageView] = [accepted, source]

    if request.requested_dub_language:
        stages.extend(_dubbing_stages(request))
    elif request.requested_subtitle_language:
        translation = _translation_stage(request)
        if request.final_path_exists:
            render = _stage(
                "subtitle_mux",
                "Build subtitles and mux video",
                StageStatus.COMPLETED,
                timestamp=request.updated_at,
            )
        elif request.job is not None and request.job.status in _FAILED_JOBS:
            render = _stage(
                "subtitle_mux",
                "Build subtitles and mux video",
                StageStatus.FAILED,
                timestamp=request.job.updated_at,
                detail=request.job.error_message,
            )
        elif source.status == StageStatus.COMPLETED and translation.status in {
            StageStatus.COMPLETED,
            StageStatus.NOT_APPLICABLE,
        }:
            render = _stage(
                "subtitle_mux",
                "Build subtitles and mux video",
                StageStatus.PENDING,
                timestamp=request.updated_at,
            )
        else:
            render = _stage(
                "subtitle_mux",
                "Build subtitles and mux video",
                StageStatus.NOT_STARTED,
            )
        stages.extend((translation, render))
    else:
        if request.final_path_exists:
            preparation_status = StageStatus.COMPLETED
        elif request.job is not None and request.job.status in _FAILED_JOBS:
            preparation_status = StageStatus.FAILED
        elif source.status == StageStatus.COMPLETED:
            preparation_status = StageStatus.PENDING
        else:
            preparation_status = StageStatus.NOT_STARTED
        stages.append(
            _stage(
                "preparation",
                "Prepare output",
                preparation_status,
                timestamp=request.updated_at if preparation_status != StageStatus.NOT_STARTED else None,
                detail=request.job.error_message
                if request.job is not None and preparation_status == StageStatus.FAILED
                else None,
            )
        )

    stages.append(_delivery_stage(request))
    stage_tuple = tuple(stages)
    state = _workflow_state(request, stage_tuple)
    error = request.delivery_error
    if error is None and request.dubbing is not None:
        error = request.dubbing.error_message
    if error is None and request.translation is not None:
        error = request.translation.error_message
    if error is None and request.job is not None:
        error = request.job.error_message
    return WorkflowView(
        id=request.job_id,
        kind=kind,
        title=title,
        state=state,
        state_label=workflow_state_label(state),
        current_stage=_current_stage(stage_tuple),
        created_at=request.created_at,
        updated_at=_latest_timestamp(stage_tuple) or request.updated_at,
        stages=stage_tuple,
        error_message=error,
        source_ingress_message_id=request.media_ingress_message_id,
    )


def _dubbing_stages(request: DownloadRequestView) -> tuple[WorkflowStageView, ...]:
    workflow = request.dubbing
    translation_evidence = _translation_stage(request)
    labels = (
        ("dubbing_inputs", "Prepare and translate inputs"),
        ("cosyvoice", "Synthesize speech with CosyVoice"),
        ("sam", "Separate background with SAM Audio"),
        ("assembly", "Assemble and mux dubbed video"),
    )
    milestone_events = (
        "content_processing.dubbing.inputs_prepared",
        "content_processing.dubbing.speech_synthesized",
        "content_processing.dubbing.background_separated",
        "content_processing.download.ready_for_delivery",
    )
    completed_from_events = [
        _outbox(request.outbox_events, event_type) for event_type in milestone_events
    ]
    if workflow is None:
        job_failed = request.job is not None and request.job.status in _FAILED_JOBS
        first = _stage(
            labels[0][0],
            labels[0][1],
            StageStatus.FAILED if job_failed else StageStatus.PENDING,
            timestamp=request.job.updated_at if job_failed and request.job else request.updated_at,
            detail=request.job.error_message if job_failed and request.job else "Waiting for workflow state",
        )
        return (first,) + tuple(
            _stage(key, label, StageStatus.NOT_STARTED) for key, label in labels[1:]
        )

    status = workflow.status
    if status in {"cancelling", "cancelled"}:
        result = []
        for index, (key, label) in enumerate(labels):
            event = completed_from_events[index]
            result.append(
                _stage(
                    key,
                    label,
                    StageStatus.COMPLETED if event is not None else StageStatus.CANCELLED,
                    timestamp=_event_time(event) or workflow.updated_at,
                    detail="Cancelled" if event is None else None,
                )
            )
            if event is None:
                result.extend(
                    _stage(k, item_label, StageStatus.NOT_STARTED)
                    for k, item_label in labels[index + 1 :]
                )
                break
        return tuple(result)

    if status == "failed":
        result = []
        failure_added = False
        for index, (key, label) in enumerate(labels):
            event = completed_from_events[index]
            if event is not None:
                result.append(
                    _stage(
                        key,
                        label,
                        StageStatus.COMPLETED,
                        timestamp=_event_time(event),
                    )
                )
            elif not failure_added:
                result.append(
                    _stage(
                        key,
                        label,
                        StageStatus.FAILED,
                        timestamp=workflow.updated_at,
                        detail=workflow.error_message,
                    )
                )
                failure_added = True
            else:
                result.append(_stage(key, label, StageStatus.NOT_STARTED))
        return tuple(result)

    rank = _DUBBING_ORDER.get(status)
    if rank is None:
        return tuple(
            _stage(
                key,
                label,
                StageStatus.UNAVAILABLE,
                timestamp=workflow.updated_at,
                detail=f"Unknown dubbing status: {status}",
            )
            for key, label in labels
        )

    # Status ranks map onto alternating ready/running phases.
    active_index = min(rank // 2, len(labels) - 1)
    result = []
    for index, (key, label) in enumerate(labels):
        event = completed_from_events[index]
        if event is not None or index < active_index or status == "ready_for_delivery":
            stage_status = StageStatus.COMPLETED
        elif index == active_index:
            stage_status = StageStatus.PENDING
        else:
            stage_status = StageStatus.NOT_STARTED
        detail = translation_evidence.detail if index == 0 else None
        if index == 0 and translation_evidence.status == StageStatus.FAILED:
            stage_status = StageStatus.FAILED
        if index == active_index and workflow.active_gpu_job_id is not None:
            detail = f"GPU job {workflow.active_gpu_job_id}"
        result.append(
            _stage(
                key,
                label,
                stage_status,
                timestamp=_event_time(event)
                or (
                    translation_evidence.timestamp
                    if index == 0 and translation_evidence.timestamp is not None
                    else (
                        workflow.updated_at
                        if stage_status in {StageStatus.PENDING, StageStatus.FAILED}
                        else None
                    )
                ),
                detail=detail,
            )
        )
    return tuple(result)


def _media_workflow(
    message: UserMessageRow,
    content: ContentProcessingView | None,
    *,
    cp_available: bool,
) -> WorkflowView | None:
    attachment = message.attachment
    if attachment is None:
        return None
    job = content.job if content is not None else None
    stages: tuple[WorkflowStageView, ...]
    if not cp_available:
        stages = (
            _stage(
                "accepted",
                "Content-processing job accepted",
                StageStatus.UNAVAILABLE,
            ),
        )
        state = WorkflowState.UNAVAILABLE
    elif job is None:
        status = StageStatus.FAILED if attachment.status == "failed" else StageStatus.PENDING
        stages = (
            _stage(
                "accepted",
                "Content-processing job accepted",
                status,
                timestamp=attachment.created_at,
                detail="No content-processing job found",
            ),
        )
        state = WorkflowState.FAILED if status == StageStatus.FAILED else WorkflowState.PENDING
    else:
        assets = content.assets if content is not None else ()
        transcript = content.transcript if content is not None else None
        downloaded = job.status in {"downloaded", "transcribing", "transcribed", "completed"} or any(
            asset.role == "source" and asset.local_path for asset in assets
        )
        has_demux = any(asset.role in {"audio", "video"} for asset in assets)
        demux_expected = attachment.type in {"video", "video_note"} or has_demux
        transcription_expected = attachment.type in {
            "voice",
            "video_note",
            "audio",
            "video",
        } or has_demux
        failed = job.status in _FAILED_JOBS
        cancelled = job.status == "cancelled"
        demux_completed = has_demux or (
            demux_expected and job.status in _SUCCESS_JOBS
        )
        transcription_completed = transcript is not None or (
            transcription_expected and job.status in _SUCCESS_JOBS
        )
        stages = (
            _stage(
                "accepted",
                "Content-processing job accepted",
                StageStatus.COMPLETED,
                timestamp=job.created_at,
                detail=job.status,
            ),
            _stage(
                "download",
                "Download media",
                StageStatus.COMPLETED
                if downloaded
                else (
                    StageStatus.FAILED
                    if failed
                    else (StageStatus.CANCELLED if cancelled else StageStatus.PENDING)
                ),
                timestamp=job.updated_at if downloaded or failed else None,
                detail=job.error_message if failed and not downloaded else None,
            ),
            _stage(
                "demux",
                "Demux audio and video",
                StageStatus.NOT_APPLICABLE
                if not demux_expected
                else (
                    StageStatus.COMPLETED
                    if demux_completed
                    else (
                        StageStatus.FAILED
                        if failed
                        else (StageStatus.CANCELLED if cancelled else StageStatus.PENDING)
                    )
                ),
                timestamp=job.updated_at if demux_completed else None,
            ),
            _stage(
                "transcription",
                "Transcribe media",
                StageStatus.NOT_APPLICABLE
                if not transcription_expected
                else (
                    StageStatus.COMPLETED
                    if transcription_completed
                    else (
                        StageStatus.FAILED
                        if failed
                        else (StageStatus.CANCELLED if cancelled else StageStatus.PENDING)
                    )
                ),
                timestamp=job.updated_at if transcription_completed or failed else None,
                detail=transcript.language if transcript is not None else None,
            ),
            _stage(
                "ingress_result",
                "Apply attachment result",
                StageStatus.COMPLETED
                if attachment.status == "ready"
                else (StageStatus.FAILED if attachment.status == "failed" else StageStatus.PENDING),
                detail=attachment.status,
            ),
        )
        if cancelled:
            state = WorkflowState.CANCELLED
        elif failed or attachment.status == "failed":
            state = WorkflowState.FAILED
        elif attachment.status == "ready" and job.status in _SUCCESS_JOBS:
            state = WorkflowState.COMPLETED
        elif job.status not in _KNOWN_JOBS:
            state = WorkflowState.UNAVAILABLE
        else:
            state = WorkflowState.RUNNING
    return WorkflowView(
        id=job.id if job is not None else attachment.id,
        kind="media_ingestion",
        title=f"{attachment.type.replace('_', ' ').title()} processing",
        state=state,
        state_label=workflow_state_label(state),
        current_stage=_current_stage(stages),
        created_at=job.created_at if job is not None else attachment.created_at,
        updated_at=_latest_timestamp(stages),
        stages=stages,
        error_message=job.error_message if job is not None else None,
        source_ingress_message_id=message.id,
    )


def _provisional_workflow(runtime: AgentRuntimeView | None) -> WorkflowView | None:
    if runtime is None or runtime.message is None:
        return None
    event = next(
        (
            item
            for item in runtime.outbox_events
            if "content_processing_handoff" in item.event_type
        ),
        None,
    )
    if event is None:
        return None
    if event.status == "failed":
        state = WorkflowState.FAILED
        stage_status = StageStatus.FAILED
    elif event.status == "published":
        state = WorkflowState.RUNNING
        stage_status = StageStatus.PENDING
    elif event.status in {"pending", "processing"}:
        state = WorkflowState.PENDING
        stage_status = StageStatus.PENDING
    else:
        state = WorkflowState.UNAVAILABLE
        stage_status = StageStatus.UNAVAILABLE
    stage = _stage(
        "handoff",
        "Create content-processing workflow",
        stage_status,
        timestamp=event.published_at or event.created_at,
        detail=event.last_error or event.status,
    )
    return WorkflowView(
        id=event.id,
        kind="workflow_handoff",
        title="Content-processing workflow",
        state=state,
        state_label=workflow_state_label(state),
        current_stage=stage.label,
        created_at=event.created_at,
        updated_at=event.published_at or event.created_at,
        stages=(stage,),
        error_message=event.last_error,
        source_ingress_message_id=None,
    )


def build_workflow_collection(
    *,
    message: UserMessageRow,
    content: ContentProcessingView | None,
    runtime: AgentRuntimeView | None,
    cp_available: bool,
) -> WorkflowCollection:
    items: list[WorkflowView] = []
    media = _media_workflow(message, content, cp_available=cp_available)
    if media is not None:
        items.append(media)
    if content is not None:
        items.extend(build_download_workflow(item) for item in content.download_requests)
    if not (content is not None and content.download_requests):
        provisional = _provisional_workflow(runtime)
        if provisional is not None:
            items.append(provisional)

    related: list[RelatedWorkflowView] = []
    if content is not None:
        for request in content.related_download_requests:
            workflow = build_download_workflow(request)
            related.append(
                RelatedWorkflowView(
                    id=workflow.id,
                    title=workflow.title,
                    state=workflow.state,
                    state_label=workflow.state_label,
                    current_stage=workflow.current_stage,
                    creator_ingress_message_id=request.creator_ingress_message_id,
                )
            )
    ordered = tuple(
        sorted(
            items,
            key=lambda item: (
                item.created_at.timestamp() if item.created_at is not None else float("-inf")
            ),
            reverse=True,
        )
    )
    runtime_pending = runtime is not None and any(
        (
            "download_handler" in event.event_type
            or "content_processing_handoff" in event.event_type
        )
        and event.status in {"pending", "processing"}
        for event in runtime.outbox_events
    )
    polling_needed = runtime_pending or any(
        item.state not in _TERMINAL_WORKFLOWS for item in ordered
    ) or any(
        item.state not in _TERMINAL_WORKFLOWS for item in related
    )
    return WorkflowCollection(
        items=ordered,
        related=tuple(related),
        polling_needed=polling_needed,
    )
