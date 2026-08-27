"""Build chronological lifecycle stages from multi-service records."""
from __future__ import annotations

from datetime import datetime

from telegram_agent.core.admin_dashboard.common.types import DbName, StageKey, StageStatus
from telegram_agent.core.admin_dashboard.services.dubbing_status import (
    dubbing_is_active,
    dubbing_is_completed,
    dubbing_is_failed,
    delivery_is_active,
)
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    ContentProcessingView,
    DownloadRequestView,
    OutboxRow,
    TimelineEvent,
    UserMessageRow,
)

_STAGE_ORDER = (
    StageKey.MESSAGE_RECEIVED,
    StageKey.ATTACHMENT_REGISTERED,
    StageKey.CP_JOB_CREATED,
    StageKey.MEDIA_DOWNLOADED,
    StageKey.MEDIA_DEMUXED,
    StageKey.TRANSCRIPTION_DONE,
    StageKey.CP_FINISHED,
    StageKey.ATTACHMENT_RESULT_APPLIED,
    StageKey.CONVERSATION_ENQUEUED,
    StageKey.CONVERSATION_DISPATCHED,
    StageKey.RUNTIME_INGESTED,
    StageKey.COORDINATED,
    # Intent classification removed from the live pipeline (download agent validates).
    StageKey.DOWNLOAD_HANDLED,
    StageKey.CONTENT_PROCESSING_HANDOFF,
    StageKey.DUBBING,
)

_CP_PIPELINE_STAGES = (
    StageKey.CP_JOB_CREATED,
    StageKey.MEDIA_DOWNLOADED,
    StageKey.MEDIA_DEMUXED,
    StageKey.TRANSCRIPTION_DONE,
    StageKey.CP_FINISHED,
)

_LABELS = {
    StageKey.MESSAGE_RECEIVED: "Message received",
    StageKey.ATTACHMENT_REGISTERED: "Attachment registered",
    StageKey.CP_JOB_CREATED: "Content-processing job created",
    StageKey.MEDIA_DOWNLOADED: "Media downloaded",
    StageKey.MEDIA_DEMUXED: "Audio/video demuxed",
    StageKey.TRANSCRIPTION_DONE: "Transcription performed",
    StageKey.CP_FINISHED: "Content-processing finished",
    StageKey.ATTACHMENT_RESULT_APPLIED: "Attachment result applied",
    StageKey.CONVERSATION_ENQUEUED: "Conversation enqueued",
    StageKey.CONVERSATION_DISPATCHED: "Dispatched to agent-runtime",
    StageKey.RUNTIME_INGESTED: "Runtime message ingested",
    StageKey.COORDINATED: "Message coordinated",
    StageKey.INTENT_CLASSIFIED: "Intent classified (legacy)",
    StageKey.DOWNLOAD_HANDLED: "Download request handled",
    StageKey.CONTENT_PROCESSING_HANDOFF: "Content-processing handoff",
    StageKey.DUBBING: "Dubbing",
}

_POST_DOWNLOAD_STATUSES = frozenset(
    {
        "downloaded",
        "transcribing",
        "transcribed",
        "completed",
    }
)
_SUCCESS_JOB_STATUSES = frozenset({"transcribed", "completed"})


def _event(
    key: StageKey,
    status: StageStatus,
    timestamp: datetime | None = None,
    detail: str | None = None,
    source_db: DbName | None = None,
) -> TimelineEvent:
    return TimelineEvent(
        key=key,
        label=_LABELS[key],
        status=status,
        timestamp=timestamp,
        detail=detail,
        source_db=source_db,
    )


def _outbox_by_type(events: tuple[OutboxRow, ...], event_type: str) -> OutboxRow | None:
    for event in events:
        if event.event_type == event_type:
            return event
    return None


def build_timeline(
    *,
    message: UserMessageRow | None,
    ingress_outbox: OutboxRow | None,
    content: ContentProcessingView | None,
    runtime: AgentRuntimeView | None,
    cp_available: bool,
    runtime_available: bool,
) -> tuple[TimelineEvent, ...]:
    if message is None:
        return ()

    has_attachment = message.attachment is not None
    events: list[TimelineEvent] = [
        _event(
            StageKey.MESSAGE_RECEIVED,
            StageStatus.COMPLETED,
            message.created_at,
            source_db=DbName.INGRESS,
        )
    ]

    if not has_attachment:
        events.append(
            _event(StageKey.ATTACHMENT_REGISTERED, StageStatus.NOT_APPLICABLE)
        )
        for key in (*_CP_PIPELINE_STAGES, StageKey.ATTACHMENT_RESULT_APPLIED):
            events.append(_event(key, StageStatus.NOT_APPLICABLE))
    else:
        att = message.attachment
        assert att is not None
        events.append(
            _event(
                StageKey.ATTACHMENT_REGISTERED,
                StageStatus.COMPLETED,
                att.created_at,
                detail=f"{att.type} / {att.status}",
                source_db=DbName.INGRESS,
            )
        )

        if not cp_available:
            for key in _CP_PIPELINE_STAGES:
                events.append(
                    _event(key, StageStatus.UNAVAILABLE, source_db=DbName.CONTENT_PROCESSING)
                )
        elif content is None or content.job is None:
            status = (
                StageStatus.FAILED
                if att.status == "failed"
                else StageStatus.NOT_STARTED
            )
            events.append(
                _event(
                    StageKey.CP_JOB_CREATED,
                    status,
                    detail="No content-processing job found"
                    if status == StageStatus.NOT_STARTED
                    else "Attachment failed before/without a job",
                    source_db=DbName.CONTENT_PROCESSING,
                )
            )
            for key in (
                StageKey.MEDIA_DOWNLOADED,
                StageKey.MEDIA_DEMUXED,
                StageKey.TRANSCRIPTION_DONE,
                StageKey.CP_FINISHED,
            ):
                events.append(_event(key, StageStatus.NOT_STARTED))
        else:
            job = content.job
            events.append(
                _event(
                    StageKey.CP_JOB_CREATED,
                    StageStatus.COMPLETED,
                    job.created_at,
                    detail=job.status,
                    source_db=DbName.CONTENT_PROCESSING,
                )
            )
            ready_evt = _outbox_by_type(
                content.outbox_events, "content_processing.job.ready"
            )
            download_done = job.status in _POST_DOWNLOAD_STATUSES or any(
                a.role == "source" and a.local_path for a in content.assets
            )
            if job.status in {"failed", "timed_out"} and not download_done:
                events.append(
                    _event(
                        StageKey.MEDIA_DOWNLOADED,
                        StageStatus.FAILED,
                        job.updated_at,
                        detail=job.error_message,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            elif download_done:
                events.append(
                    _event(
                        StageKey.MEDIA_DOWNLOADED,
                        StageStatus.COMPLETED,
                        ready_evt.published_at if ready_evt else job.updated_at,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            elif job.status in {"queued", "running"}:
                events.append(
                    _event(
                        StageKey.MEDIA_DOWNLOADED,
                        StageStatus.PENDING,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            else:
                events.append(_event(StageKey.MEDIA_DOWNLOADED, StageStatus.NOT_STARTED))

            has_demux = any(a.role in {"audio", "video"} for a in content.assets)
            # Documents may demux when Telegram delivers a video container (MKV).
            demux_expected = att.type in {"video", "video_note"} or has_demux
            if demux_expected:
                if has_demux:
                    events.append(
                        _event(
                            StageKey.MEDIA_DEMUXED,
                            StageStatus.COMPLETED,
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                elif job.status in {"failed", "timed_out"}:
                    events.append(
                        _event(
                            StageKey.MEDIA_DEMUXED,
                            StageStatus.FAILED,
                            detail=job.error_message,
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                elif job.status in {"queued", "running"}:
                    events.append(
                        _event(
                            StageKey.MEDIA_DEMUXED,
                            StageStatus.PENDING,
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                else:
                    events.append(_event(StageKey.MEDIA_DEMUXED, StageStatus.NOT_STARTED))
            else:
                events.append(_event(StageKey.MEDIA_DEMUXED, StageStatus.NOT_APPLICABLE))

            transcription_expected = (
                att.type in {"voice", "video_note", "audio", "video"}
                or has_demux
                or content.transcript is not None
            )
            if content.transcript is not None:
                events.append(
                    _event(
                        StageKey.TRANSCRIPTION_DONE,
                        StageStatus.COMPLETED,
                        detail=content.transcript.language,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            elif transcription_expected:
                if job.status == "transcribing":
                    events.append(
                        _event(
                            StageKey.TRANSCRIPTION_DONE,
                            StageStatus.PENDING,
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                elif job.status in {"failed", "timed_out"}:
                    events.append(
                        _event(
                            StageKey.TRANSCRIPTION_DONE,
                            StageStatus.FAILED,
                            detail=job.error_message,
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                elif job.status in _SUCCESS_JOB_STATUSES:
                    events.append(
                        _event(
                            StageKey.TRANSCRIPTION_DONE,
                            StageStatus.NOT_STARTED,
                            detail="Completed without transcript row",
                            source_db=DbName.CONTENT_PROCESSING,
                        )
                    )
                else:
                    events.append(
                        _event(StageKey.TRANSCRIPTION_DONE, StageStatus.NOT_STARTED)
                    )
            else:
                events.append(
                    _event(StageKey.TRANSCRIPTION_DONE, StageStatus.NOT_APPLICABLE)
                )

            if job.status in _SUCCESS_JOB_STATUSES:
                events.append(
                    _event(
                        StageKey.CP_FINISHED,
                        StageStatus.COMPLETED,
                        job.updated_at,
                        detail=job.status,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            elif job.status in {"failed", "timed_out"}:
                events.append(
                    _event(
                        StageKey.CP_FINISHED,
                        StageStatus.FAILED,
                        job.updated_at,
                        detail=job.error_message,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )
            else:
                events.append(
                    _event(
                        StageKey.CP_FINISHED,
                        StageStatus.PENDING,
                        detail=job.status,
                        source_db=DbName.CONTENT_PROCESSING,
                    )
                )

        if att.status == "ready":
            events.append(
                _event(
                    StageKey.ATTACHMENT_RESULT_APPLIED,
                    StageStatus.COMPLETED,
                    detail="ready",
                    source_db=DbName.INGRESS,
                )
            )
        elif att.status == "failed":
            events.append(
                _event(
                    StageKey.ATTACHMENT_RESULT_APPLIED,
                    StageStatus.FAILED,
                    detail="failed",
                    source_db=DbName.INGRESS,
                )
            )
        elif att.status == "processing":
            events.append(
                _event(
                    StageKey.ATTACHMENT_RESULT_APPLIED,
                    StageStatus.PENDING,
                    source_db=DbName.INGRESS,
                )
            )
        else:
            events.append(
                _event(
                    StageKey.ATTACHMENT_RESULT_APPLIED,
                    StageStatus.NOT_STARTED,
                    source_db=DbName.INGRESS,
                )
            )

    # Conversation outbox / dispatch
    if message.conversation_status in {"enqueued", "dispatched", "failed"} or ingress_outbox:
        if ingress_outbox is not None:
            if ingress_outbox.status == "failed" or message.conversation_status == "failed":
                enq_status = StageStatus.FAILED
            else:
                enq_status = StageStatus.COMPLETED
            events.append(
                _event(
                    StageKey.CONVERSATION_ENQUEUED,
                    enq_status,
                    ingress_outbox.created_at,
                    detail=ingress_outbox.status,
                    source_db=DbName.INGRESS,
                )
            )
            if ingress_outbox.status == "published" or message.conversation_status == "dispatched":
                events.append(
                    _event(
                        StageKey.CONVERSATION_DISPATCHED,
                        StageStatus.COMPLETED,
                        ingress_outbox.published_at,
                        source_db=DbName.INGRESS,
                    )
                )
            elif ingress_outbox.status == "failed":
                events.append(
                    _event(
                        StageKey.CONVERSATION_DISPATCHED,
                        StageStatus.FAILED,
                        detail=ingress_outbox.last_error,
                        source_db=DbName.INGRESS,
                    )
                )
            else:
                events.append(
                    _event(
                        StageKey.CONVERSATION_DISPATCHED,
                        StageStatus.PENDING,
                        source_db=DbName.INGRESS,
                    )
                )
        else:
            events.append(
                _event(StageKey.CONVERSATION_ENQUEUED, StageStatus.PENDING, source_db=DbName.INGRESS)
            )
            events.append(
                _event(StageKey.CONVERSATION_DISPATCHED, StageStatus.NOT_STARTED, source_db=DbName.INGRESS)
            )
    else:
        events.append(
            _event(StageKey.CONVERSATION_ENQUEUED, StageStatus.NOT_STARTED, source_db=DbName.INGRESS)
        )
        events.append(
            _event(StageKey.CONVERSATION_DISPATCHED, StageStatus.NOT_STARTED, source_db=DbName.INGRESS)
        )

    # Runtime
    outbox_events: tuple[OutboxRow, ...] = ()
    if runtime is not None:
        if runtime.outbox_events:
            outbox_events = runtime.outbox_events
        elif runtime.outbox is not None:
            outbox_events = (runtime.outbox,)
    coordination_outbox = next(
        (e for e in outbox_events if "pending_coordination" in e.event_type),
        outbox_events[0] if outbox_events else None,
    )

    download_outbox = next(
        (e for e in outbox_events if "download_handler" in e.event_type),
        None,
    )
    handoff_outbox = next(
        (e for e in outbox_events if "content_processing" in e.event_type),
        None,
    )
    agent_messages = runtime.agent_messages if runtime is not None else ()
    download_agent_message = next(
        (
            item
            for item in agent_messages
            if item.role == "download_agent"
            and runtime is not None
            and runtime.message is not None
            and item.ingress_message_id == runtime.message.ingress_message_id
        ),
        None,
    )

    def _append_handoff_stage() -> None:
        if handoff_outbox is None:
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.NOT_APPLICABLE,
                    detail="no handoff (incomplete group or non-download request)",
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
        elif handoff_outbox.status == "failed":
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.FAILED,
                    detail=handoff_outbox.last_error,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
        elif handoff_outbox.status == "published":
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.COMPLETED,
                    handoff_outbox.published_at,
                    detail="content-processing notified",
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
        else:
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.PENDING,
                    detail=handoff_outbox.status,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )

    if not runtime_available:
        events.append(_event(StageKey.RUNTIME_INGESTED, StageStatus.UNAVAILABLE, source_db=DbName.AGENT_RUNTIME))
        events.append(_event(StageKey.COORDINATED, StageStatus.UNAVAILABLE, source_db=DbName.AGENT_RUNTIME))
        events.append(_event(StageKey.DOWNLOAD_HANDLED, StageStatus.UNAVAILABLE, source_db=DbName.AGENT_RUNTIME))
        events.append(
            _event(
                StageKey.CONTENT_PROCESSING_HANDOFF,
                StageStatus.UNAVAILABLE,
                source_db=DbName.AGENT_RUNTIME,
            )
        )
    elif runtime is None or runtime.message is None:
        events.append(_event(StageKey.RUNTIME_INGESTED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME))
        events.append(_event(StageKey.COORDINATED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME))
        events.append(_event(StageKey.DOWNLOAD_HANDLED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME))
        events.append(
            _event(
                StageKey.CONTENT_PROCESSING_HANDOFF,
                StageStatus.NOT_STARTED,
                source_db=DbName.AGENT_RUNTIME,
            )
        )
    else:
        rm = runtime.message
        events.append(
            _event(
                StageKey.RUNTIME_INGESTED,
                StageStatus.COMPLETED,
                rm.created_at,
                detail=f"pipeline={rm.status}",
                source_db=DbName.AGENT_RUNTIME,
            )
        )
        if rm.status == "failed" and rm.coordination_status != "grouped":
            events.append(
                _event(
                    StageKey.COORDINATED,
                    StageStatus.FAILED,
                    rm.coordinated_at,
                    detail=rm.coordination_status,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
            events.append(
                _event(StageKey.DOWNLOAD_HANDLED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME)
            )
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.NOT_STARTED,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
        elif rm.coordination_status in {"grouped", "vague"}:
            detail = rm.coordination_status
            if runtime.group is not None:
                detail = f"{rm.coordination_status} group #{runtime.group.group_number}"
            events.append(
                _event(
                    StageKey.COORDINATED,
                    StageStatus.COMPLETED,
                    rm.coordinated_at,
                    detail=detail,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )

            # Download handler + content-processing handoff (no intent step).
            if rm.coordination_status == "vague":
                events.append(
                    _event(
                        StageKey.DOWNLOAD_HANDLED,
                        StageStatus.NOT_APPLICABLE,
                        detail="vague messages skip download handling",
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
                events.append(
                    _event(
                        StageKey.CONTENT_PROCESSING_HANDOFF,
                        StageStatus.NOT_APPLICABLE,
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
            elif download_agent_message is not None:
                events.append(
                    _event(
                        StageKey.DOWNLOAD_HANDLED,
                        StageStatus.COMPLETED,
                        download_agent_message.created_at,
                        detail=f"role={download_agent_message.role}",
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
                if handoff_outbox is None:
                    events.append(
                        _event(
                            StageKey.CONTENT_PROCESSING_HANDOFF,
                            StageStatus.NOT_STARTED,
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
                else:
                    _append_handoff_stage()
            elif download_outbox is not None:
                if download_outbox.status == "failed":
                    events.append(
                        _event(
                            StageKey.DOWNLOAD_HANDLED,
                            StageStatus.FAILED,
                            detail=download_outbox.last_error,
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
                    events.append(
                        _event(
                            StageKey.CONTENT_PROCESSING_HANDOFF,
                            StageStatus.NOT_STARTED,
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
                elif download_outbox.status == "published":
                    events.append(
                        _event(
                            StageKey.DOWNLOAD_HANDLED,
                            StageStatus.COMPLETED,
                            download_outbox.published_at,
                            detail="published (early-exit, rejected, or completed)",
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
                    _append_handoff_stage()
                else:
                    events.append(
                        _event(
                            StageKey.DOWNLOAD_HANDLED,
                            StageStatus.PENDING,
                            detail=download_outbox.status,
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
                    events.append(
                        _event(
                            StageKey.CONTENT_PROCESSING_HANDOFF,
                            StageStatus.NOT_STARTED,
                            source_db=DbName.AGENT_RUNTIME,
                        )
                    )
            elif rm.coordination_status == "grouped" and rm.status in {
                "coordinated",
                "classified",  # legacy rows
            }:
                events.append(
                    _event(
                        StageKey.DOWNLOAD_HANDLED,
                        StageStatus.PENDING,
                        detail="awaiting download handler",
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
                events.append(
                    _event(
                        StageKey.CONTENT_PROCESSING_HANDOFF,
                        StageStatus.NOT_STARTED,
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
            else:
                events.append(
                    _event(
                        StageKey.DOWNLOAD_HANDLED,
                        StageStatus.NOT_STARTED,
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
                events.append(
                    _event(
                        StageKey.CONTENT_PROCESSING_HANDOFF,
                        StageStatus.NOT_STARTED,
                        source_db=DbName.AGENT_RUNTIME,
                    )
                )
        elif coordination_outbox is not None and coordination_outbox.status == "failed":
            events.append(
                _event(
                    StageKey.COORDINATED,
                    StageStatus.FAILED,
                    detail=coordination_outbox.last_error,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
            events.append(
                _event(StageKey.DOWNLOAD_HANDLED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME)
            )
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.NOT_STARTED,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
        else:
            events.append(
                _event(
                    StageKey.COORDINATED,
                    StageStatus.PENDING,
                    detail=rm.status,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )
            events.append(
                _event(StageKey.DOWNLOAD_HANDLED, StageStatus.NOT_STARTED, source_db=DbName.AGENT_RUNTIME)
            )
            events.append(
                _event(
                    StageKey.CONTENT_PROCESSING_HANDOFF,
                    StageStatus.NOT_STARTED,
                    source_db=DbName.AGENT_RUNTIME,
                )
            )

    events.append(_dubbing_event(content=content, cp_available=cp_available))

    # Stable order
    by_key = {event.key: event for event in events}
    ordered = tuple(by_key[key] for key in _STAGE_ORDER if key in by_key)
    return ordered


def _latest_download_request(
    content: ContentProcessingView | None,
) -> DownloadRequestView | None:
    if content is None or not content.download_requests:
        return None
    return content.download_requests[0]


def _dubbing_event(
    *,
    content: ContentProcessingView | None,
    cp_available: bool,
) -> TimelineEvent:
    if not cp_available:
        return _event(
            StageKey.DUBBING,
            StageStatus.UNAVAILABLE,
            source_db=DbName.CONTENT_PROCESSING,
        )
    request = _latest_download_request(content)
    if request is None or not request.requested_dub_language:
        return _event(
            StageKey.DUBBING,
            StageStatus.NOT_APPLICABLE,
            detail="no dubbing request",
            source_db=DbName.CONTENT_PROCESSING,
        )
    workflow = request.dubbing
    if workflow is None:
        if request.job is not None and request.job.status in {"failed", "timed_out"}:
            return _event(
                StageKey.DUBBING,
                StageStatus.FAILED,
                request.job.updated_at,
                detail=request.job.error_message or request.job.status,
                source_db=DbName.CONTENT_PROCESSING,
            )
        return _event(
            StageKey.DUBBING,
            StageStatus.PENDING,
            request.updated_at,
            detail=f"target={request.requested_dub_language}",
            source_db=DbName.CONTENT_PROCESSING,
        )
    detail = workflow.status_label
    if workflow.active_gpu_job_id is not None and dubbing_is_active(workflow.status):
        detail = f"{detail} · gpu {workflow.active_gpu_job_id}"
    if workflow.error_message:
        detail = f"{detail}: {workflow.error_message}"
    if dubbing_is_failed(workflow.status):
        status = StageStatus.FAILED
    elif dubbing_is_completed(workflow.status) and not delivery_is_active(
        request.delivery_status
    ):
        status = StageStatus.COMPLETED
    elif dubbing_is_completed(workflow.status):
        status = StageStatus.PENDING
        detail = f"{detail} · delivery {request.delivery_status}"
    else:
        status = StageStatus.PENDING
    return _event(
        StageKey.DUBBING,
        status,
        workflow.updated_at,
        detail=detail,
        source_db=DbName.CONTENT_PROCESSING,
    )
