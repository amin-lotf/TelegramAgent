from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from telegram_agent.core.admin_dashboard_v2.common.types import (
    DataSourceStatus,
    LifecycleStageView,
    SourceResult,
    StageStatus,
    TimelineEventView,
)


_TRANSCRIBABLE = {"audio", "video", "video_note", "voice"}
_DEMUXED = {"video", "video_note"}


def build_lifecycle_and_timeline(
    ingress: SourceResult[dict[str, Any]],
    content: SourceResult[dict[str, Any]],
    runtime: SourceResult[dict[str, Any]],
) -> tuple[tuple[LifecycleStageView, ...], tuple[TimelineEventView, ...]]:
    stages: list[LifecycleStageView] = []
    events: list[TimelineEventView] = []

    ingress_data = ingress.data or {}
    message = ingress_data.get("message")
    attachment = ingress_data.get("attachment")
    ingress_outbox = ingress_data.get("outbox")
    content_attempts = (content.data or {}).get("attempts", [])
    runtime_data = runtime.data or {}
    runtime_message = runtime_data.get("message")
    runtime_outbox = runtime_data.get("outbox")
    claim = runtime_data.get("claim")

    if message:
        stages.append(_stage("ingress_persisted", "Ingress message persisted", "telegram_ingress", StageStatus.COMPLETED))
        events.append(_event("ingress_persisted", "telegram_ingress", "Ingress message persisted", StageStatus.COMPLETED, message.get("created_at"), message.get("id")))
    else:
        stages.append(_missing_stage("ingress_persisted", "Ingress message persisted", "telegram_ingress", ingress.status))

    if attachment:
        attachment_status = str(attachment["status"])
        stages.append(_stage("attachment_registered", "Attachment registered", "telegram_ingress", StageStatus.COMPLETED))
        events.append(_event("attachment_registered", "telegram_ingress", "Attachment registered", StageStatus.COMPLETED, attachment.get("created_at"), attachment.get("id")))
    else:
        attachment_status = "not_applicable"
        stages.append(_stage("attachment_registered", "Attachment registered", "telegram_ingress", StageStatus.NOT_APPLICABLE))

    if attachment or content_attempts:
        if content_attempts:
            first = content_attempts[0]
            stages.append(_stage("content_job", "Content-processing job accepted", "content_processing", StageStatus.COMPLETED))
            events.append(_event("content_job", "content_processing", "Content-processing job accepted", StageStatus.COMPLETED, first.get("created_at"), first.get("job_id")))
        else:
            status = _downstream_missing(content.status, failed=attachment_status == "failed")
            stages.append(_stage("content_job", "Content-processing job accepted", "content_processing", status, "No matching content job"))
    else:
        stages.append(_stage("content_job", "Content-processing job accepted", "content_processing", StageStatus.NOT_APPLICABLE))

    attachment_type = None
    if attachment:
        attachment_type = str(attachment.get("type"))
    elif content_attempts:
        attachment_type = str(content_attempts[0].get("attachment_type"))

    if attachment_type:
        best = content_attempts[-1] if content_attempts else None
        job_status = str(best["status"]) if best else None
        download_status = _download_stage_status(job_status, content.status)
        stages.append(_stage("media_download", "Media downloaded", "content_processing", download_status, _job_detail(best)))

        if attachment_type in _DEMUXED:
            assets = best.get("assets", []) if best else []
            roles = {str(asset.get("role")) for asset in assets}
            demux_status = (
                StageStatus.COMPLETED
                if {"audio", "video"}.issubset(roles)
                else StageStatus.FAILED
                if job_status == "failed"
                else StageStatus.PENDING
                if job_status in {"queued", "running"}
                else StageStatus.UNKNOWN
            )
            stages.append(_stage("media_demux", "Audio/video demultiplexed", "content_processing", demux_status, "Exact timestamp unavailable"))
        else:
            stages.append(_stage("media_demux", "Audio/video demultiplexed", "content_processing", StageStatus.NOT_APPLICABLE))

        if attachment_type in _TRANSCRIBABLE:
            transcript = best.get("transcript") if best else None
            transcription_status = (
                StageStatus.COMPLETED
                if transcript
                else StageStatus.FAILED
                if job_status == "failed"
                else StageStatus.PENDING
                if job_status in {"queued", "running", "downloaded", "transcribing"}
                else StageStatus.UNKNOWN
            )
            stages.append(_stage("transcription", "Transcription performed", "content_processing", transcription_status, "Exact transcript timestamp unavailable"))
        else:
            stages.append(_stage("transcription", "Transcription performed", "content_processing", StageStatus.NOT_APPLICABLE))

        callback_events = [
            event
            for attempt in content_attempts
            for event in attempt.get("outbox_events", [])
            if event.get("event_type") == "content_processing.job.finished"
        ]
        callback_status = (
            StageStatus.COMPLETED
            if callback_events
            else StageStatus.FAILED
            if job_status == "failed" and not callback_events
            else StageStatus.PENDING
            if job_status in {"queued", "running", "downloaded", "transcribing"}
            else StageStatus.NOT_STARTED
        )
        stages.append(_stage("callback_enqueued", "Ingress callback task enqueued", "content_processing", callback_status))
        for item in callback_events:
            events.append(_event("callback_enqueued", "content_processing", "Ingress callback task enqueued", StageStatus.COMPLETED, item.get("created_at"), item.get("id")))
        observed_status = (
            StageStatus.COMPLETED
            if attachment_status == "ready"
            else StageStatus.FAILED
            if attachment_status == "failed"
            else StageStatus.PENDING
        )
        stages.append(_stage("callback_observed", "Processing result observed by ingress", "telegram_ingress", observed_status, "Ingress has no status-change timestamp"))
    else:
        for key, label in (
            ("media_download", "Media downloaded"),
            ("media_demux", "Audio/video demultiplexed"),
            ("transcription", "Transcription performed"),
            ("callback_enqueued", "Ingress callback task enqueued"),
            ("callback_observed", "Processing result observed by ingress"),
        ):
            stages.append(_stage(key, label, "content_processing", StageStatus.NOT_APPLICABLE))

    if ingress_outbox:
        outbox_status = str(ingress_outbox["status"])
        stages.append(_stage("conversation_enqueued", "Conversation batch enqueued", "telegram_ingress", StageStatus.FAILED if outbox_status == "failed" else StageStatus.COMPLETED))
        events.append(_event("conversation_enqueued", "telegram_ingress", "Conversation batch enqueued", StageStatus.COMPLETED, ingress_outbox.get("created_at"), ingress_outbox.get("id")))
        if ingress_outbox.get("published_at"):
            events.append(_event("conversation_published", "telegram_ingress", "Runtime accepted conversation batch", StageStatus.COMPLETED, ingress_outbox.get("published_at"), ingress_outbox.get("id")))
    else:
        conversation_state = str(message.get("conversation_status")) if message else None
        status = StageStatus.FAILED if conversation_state == "failed" else StageStatus.PENDING if message else _downstream_missing(ingress.status)
        stages.append(_stage("conversation_enqueued", "Conversation batch enqueued", "telegram_ingress", status))

    if runtime_message:
        stages.append(_stage("runtime_accepted", "Runtime message persisted", "agent_runtime", StageStatus.COMPLETED))
        events.append(_event("runtime_accepted", "agent_runtime", "Runtime message persisted", StageStatus.COMPLETED, runtime_message.get("created_at"), runtime_message.get("id")))
        coordination_status = str(runtime_message["coordination_status"])
        coord_stage_status = (
            StageStatus.FAILED
            if runtime_outbox and runtime_outbox.get("status") == "failed"
            else StageStatus.COMPLETED
            if coordination_status in {"grouped", "vague"}
            else StageStatus.PENDING
        )
        detail = "Conversation claim is active" if claim and claim.get("status") == "claimed" else None
        stages.append(_stage("runtime_coordination", "Runtime conversation coordinated", "agent_runtime", coord_stage_status, detail))
        if runtime_message.get("coordinated_at"):
            events.append(_event("runtime_coordination", "agent_runtime", f"Runtime decision: {coordination_status}", coord_stage_status, runtime_message.get("coordinated_at"), runtime_message.get("id")))
    else:
        ingress_conversation_status = str(message.get("conversation_status")) if message else None
        missing = (
            StageStatus.PENDING
            if ingress_conversation_status in {"pending", "enqueued", "dispatched"}
            else _downstream_missing(runtime.status)
        )
        stages.append(_stage("runtime_accepted", "Runtime message persisted", "agent_runtime", missing))
        stages.append(_stage("runtime_coordination", "Runtime conversation coordinated", "agent_runtime", missing))

    stages.extend(
        (
            _stage("agent_execution", "Agent execution completed", "agent_runtime", StageStatus.NOT_IMPLEMENTED, "No current source-of-truth record exists"),
            _stage("response_prepared", "Outgoing response prepared", "agent_runtime", StageStatus.NOT_IMPLEMENTED, "No current source-of-truth record exists"),
            _stage("telegram_response_sent", "Telegram response sent", "telegram_ingress", StageStatus.NOT_IMPLEMENTED, "No current source-of-truth record exists"),
        )
    )

    for attempt in content_attempts:
        for outbox in attempt.get("outbox_events", []):
            events.append(_event(
                f"content_outbox:{outbox.get('event_type')}",
                "content_processing",
                str(outbox.get("event_type")),
                StageStatus.FAILED if outbox.get("status") == "failed" else StageStatus.COMPLETED if outbox.get("published_at") else StageStatus.PENDING,
                outbox.get("created_at"),
                outbox.get("id"),
            ))
    events.sort(key=lambda item: (_timestamp_key(item.timestamp), item.service, item.key, item.record_id or ""))
    return tuple(stages), tuple(events)


def _stage(key: str, label: str, service: str, status: StageStatus, detail: str | None = None) -> LifecycleStageView:
    return LifecycleStageView(key=key, label=label, service=service, status=status, detail=detail)


def _event(key: str, service: str, label: str, status: StageStatus, timestamp: Any, record_id: Any) -> TimelineEventView:
    return TimelineEventView(key=key, service=service, label=label, status=status, timestamp=timestamp if isinstance(timestamp, datetime) else None, record_id=str(record_id) if record_id is not None else None)


def _missing_stage(key: str, label: str, service: str, source_status: DataSourceStatus) -> LifecycleStageView:
    return _stage(key, label, service, _downstream_missing(source_status))


def _downstream_missing(source_status: DataSourceStatus, *, failed: bool = False) -> StageStatus:
    if failed:
        return StageStatus.FAILED
    if source_status in {DataSourceStatus.UNAVAILABLE, DataSourceStatus.TIMED_OUT, DataSourceStatus.INVALID_SCHEMA, DataSourceStatus.NOT_CONFIGURED}:
        return StageStatus.UNKNOWN
    return StageStatus.NOT_STARTED


def _download_stage_status(job_status: str | None, source_status: DataSourceStatus) -> StageStatus:
    if job_status in {"downloaded", "transcribing", "completed"}:
        return StageStatus.COMPLETED
    if job_status == "failed":
        return StageStatus.FAILED
    if job_status in {"queued", "running"}:
        return StageStatus.PENDING
    return _downstream_missing(source_status)


def _job_detail(attempt: dict[str, Any] | None) -> str | None:
    if not attempt:
        return None
    if attempt.get("error_message"):
        return str(attempt["error_message"])
    return "Exact download timestamp unavailable"


def _timestamp_key(value: datetime | None) -> datetime:
    return value or datetime.max.replace(tzinfo=timezone.utc)
