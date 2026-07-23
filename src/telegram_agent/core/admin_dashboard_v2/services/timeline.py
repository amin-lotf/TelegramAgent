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

        assets = best.get("assets", []) if best else []
        roles = {str(asset.get("role")) for asset in assets}
        has_demux_assets = {"audio", "video"}.issubset(roles)
        # Documents may still demux when the payload is a video container (MKV).
        demux_expected = attachment_type in _DEMUXED or has_demux_assets
        if demux_expected:
            demux_status = (
                StageStatus.COMPLETED
                if has_demux_assets
                else StageStatus.FAILED
                if job_status == "failed"
                else StageStatus.PENDING
                if job_status in {"queued", "running"}
                else StageStatus.UNKNOWN
            )
            stages.append(_stage("media_demux", "Audio/video demultiplexed", "content_processing", demux_status, "Exact timestamp unavailable"))
        else:
            stages.append(_stage("media_demux", "Audio/video demultiplexed", "content_processing", StageStatus.NOT_APPLICABLE))

        transcript = best.get("transcript") if best else None
        transcription_expected = (
            attachment_type in _TRANSCRIBABLE
            or has_demux_assets
            or transcript is not None
        )
        if transcription_expected:
            transcription_status = (
                StageStatus.COMPLETED
                if transcript
                else StageStatus.FAILED
                if job_status == "failed"
                else StageStatus.PENDING
                if job_status in {
                    "queued",
                    "running",
                    "downloaded",
                    "transcribing",
                    "transcribed",
                    "chunking",
                }
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
            if job_status in {
                "queued",
                "running",
                "downloaded",
                "transcribing",
                "transcribed",
                "chunking",
            }
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

    runtime_outbox_events = runtime_data.get("outbox_events") or (
        [runtime_outbox] if runtime_outbox else []
    )
    intent_outbox = next(
        (
            event
            for event in runtime_outbox_events
            if event and "intent" in str(event.get("event_type") or "")
        ),
        None,
    )
    coordination_outbox = next(
        (
            event
            for event in runtime_outbox_events
            if event and "pending_coordination" in str(event.get("event_type") or "")
        ),
        runtime_outbox,
    )

    if runtime_message:
        pipeline_status = str(runtime_message.get("status") or "received")
        stages.append(
            _stage(
                "runtime_accepted",
                "Runtime message persisted",
                "agent_runtime",
                StageStatus.COMPLETED,
                f"pipeline={pipeline_status}",
            )
        )
        events.append(
            _event(
                "runtime_accepted",
                "agent_runtime",
                "Runtime message persisted",
                StageStatus.COMPLETED,
                runtime_message.get("created_at"),
                runtime_message.get("id"),
            )
        )
        coordination_status = str(runtime_message["coordination_status"])
        if pipeline_status == "failed" and coordination_status != "grouped":
            coord_stage_status = StageStatus.FAILED
        elif coordination_outbox and coordination_outbox.get("status") == "failed":
            coord_stage_status = StageStatus.FAILED
        elif coordination_status in {"grouped", "vague"}:
            coord_stage_status = StageStatus.COMPLETED
        else:
            coord_stage_status = StageStatus.PENDING
        detail = f"pipeline={pipeline_status}"
        if claim and claim.get("status") == "claimed":
            detail = f"{detail}; conversation claim is active"
        stages.append(
            _stage(
                "runtime_coordination",
                "Runtime conversation coordinated",
                "agent_runtime",
                coord_stage_status,
                detail,
            )
        )
        if runtime_message.get("coordinated_at"):
            events.append(
                _event(
                    "runtime_coordination",
                    "agent_runtime",
                    f"Runtime decision: {coordination_status}",
                    coord_stage_status,
                    runtime_message.get("coordinated_at"),
                    runtime_message.get("id"),
                )
            )

        if pipeline_status == "classified":
            intent_status = StageStatus.COMPLETED
            intent_detail = str(runtime_message.get("intent") or "classified")
        elif pipeline_status == "failed" and coordination_status == "grouped":
            intent_status = StageStatus.FAILED
            intent_detail = (
                str(intent_outbox.get("last_error"))
                if intent_outbox and intent_outbox.get("last_error")
                else "classification failed"
            )
        elif coordination_status == "vague":
            intent_status = StageStatus.NOT_APPLICABLE
            intent_detail = "vague messages are not classified"
        elif intent_outbox and intent_outbox.get("status") == "failed":
            intent_status = StageStatus.FAILED
            intent_detail = str(intent_outbox.get("last_error") or "intent outbox failed")
        elif coordination_status == "grouped":
            intent_status = StageStatus.PENDING
            intent_detail = pipeline_status
        else:
            intent_status = StageStatus.NOT_STARTED
            intent_detail = None
        stages.append(
            _stage(
                "intent_classified",
                "Intent classified",
                "agent_runtime",
                intent_status,
                intent_detail,
            )
        )
        if pipeline_status == "classified":
            events.append(
                _event(
                    "intent_classified",
                    "agent_runtime",
                    f"Intent: {runtime_message.get('intent')}",
                    StageStatus.COMPLETED,
                    runtime_message.get("coordinated_at"),
                    runtime_message.get("id"),
                )
            )

        download_outbox = next(
            (
                event
                for event in runtime_outbox_events
                if event and "download_handler" in str(event.get("event_type") or "")
            ),
            None,
        )
        handoff_outbox = next(
            (
                event
                for event in runtime_outbox_events
                if event
                and "content_processing" in str(event.get("event_type") or "")
            ),
            None,
        )
        agent_messages = runtime_data.get("agent_messages") or []
        download_agent_message = next(
            (
                item
                for item in agent_messages
                if str(item.get("role") or "") == "download_agent"
            ),
            agent_messages[0] if agent_messages else None,
        )
        intent = str(runtime_message.get("intent") or "")

        if intent == "conversation":
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.NOT_APPLICABLE,
                    "conversation intent has no download handler",
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_APPLICABLE,
                    "conversation intent has no content-processing handoff",
                )
            )
        elif pipeline_status == "failed" and download_outbox and download_outbox.get("status") == "failed":
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.FAILED,
                    str(download_outbox.get("last_error") or "download handler failed"),
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_STARTED,
                )
            )
        elif download_agent_message is not None:
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.COMPLETED,
                    f"role={download_agent_message.get('role')}",
                )
            )
            events.append(
                _event(
                    "download_handler",
                    "agent_runtime",
                    "Download agent message recorded",
                    StageStatus.COMPLETED,
                    download_agent_message.get("created_at"),
                    download_agent_message.get("id"),
                )
            )
            if handoff_outbox is None:
                stages.append(
                    _stage(
                        "content_processing_handoff",
                        "Content-processing handoff",
                        "agent_runtime",
                        StageStatus.NOT_STARTED,
                    )
                )
            elif handoff_outbox.get("status") == "failed":
                stages.append(
                    _stage(
                        "content_processing_handoff",
                        "Content-processing handoff",
                        "agent_runtime",
                        StageStatus.FAILED,
                        str(handoff_outbox.get("last_error") or "handoff failed"),
                    )
                )
            elif handoff_outbox.get("status") == "published":
                stages.append(
                    _stage(
                        "content_processing_handoff",
                        "Content-processing handoff",
                        "agent_runtime",
                        StageStatus.COMPLETED,
                        "content-processing notified",
                    )
                )
                events.append(
                    _event(
                        "content_processing_handoff",
                        "agent_runtime",
                        "Content-processing handoff published",
                        StageStatus.COMPLETED,
                        handoff_outbox.get("published_at") or handoff_outbox.get("created_at"),
                        handoff_outbox.get("id"),
                    )
                )
            else:
                stages.append(
                    _stage(
                        "content_processing_handoff",
                        "Content-processing handoff",
                        "agent_runtime",
                        StageStatus.PENDING,
                        str(handoff_outbox.get("status")),
                    )
                )
        elif download_outbox is not None:
            if download_outbox.get("status") == "failed":
                dl_status = StageStatus.FAILED
                dl_detail = str(download_outbox.get("last_error") or "download handler failed")
            elif download_outbox.get("status") == "published":
                # Early-exit publishes without creating AgentMessage.
                dl_status = StageStatus.COMPLETED
                dl_detail = "early-exit or completed without agent message"
            else:
                dl_status = StageStatus.PENDING
                dl_detail = str(download_outbox.get("status"))
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    dl_status,
                    dl_detail,
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_STARTED
                    if dl_status != StageStatus.FAILED
                    else StageStatus.NOT_STARTED,
                )
            )
        elif pipeline_status == "classified" and intent == "download_request":
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.PENDING,
                    "awaiting download handler outbox",
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_STARTED,
                )
            )
        elif pipeline_status == "classified":
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.NOT_APPLICABLE,
                    intent or "no download intent",
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_APPLICABLE,
                )
            )
        else:
            stages.append(
                _stage(
                    "download_handler",
                    "Download request handled",
                    "agent_runtime",
                    StageStatus.NOT_STARTED,
                )
            )
            stages.append(
                _stage(
                    "content_processing_handoff",
                    "Content-processing handoff",
                    "agent_runtime",
                    StageStatus.NOT_STARTED,
                )
            )
    else:
        ingress_conversation_status = str(message.get("conversation_status")) if message else None
        missing = (
            StageStatus.PENDING
            if ingress_conversation_status in {"pending", "enqueued", "dispatched"}
            else _downstream_missing(runtime.status)
        )
        stages.append(_stage("runtime_accepted", "Runtime message persisted", "agent_runtime", missing))
        stages.append(_stage("runtime_coordination", "Runtime conversation coordinated", "agent_runtime", missing))
        stages.append(_stage("intent_classified", "Intent classified", "agent_runtime", missing))
        stages.append(_stage("download_handler", "Download request handled", "agent_runtime", missing))
        stages.append(
            _stage(
                "content_processing_handoff",
                "Content-processing handoff",
                "agent_runtime",
                missing,
            )
        )

    stages.extend(
        (
            _stage(
                "response_prepared",
                "Outgoing response prepared",
                "agent_runtime",
                StageStatus.NOT_IMPLEMENTED,
                "No durable response-prep record yet",
            ),
            _stage(
                "telegram_response_sent",
                "Telegram response sent",
                "telegram_ingress",
                StageStatus.NOT_IMPLEMENTED,
                "No durable send receipt yet",
            ),
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
    if job_status in {
        "downloaded",
        "transcribing",
        "transcribed",
        "chunking",
        "chunked",
        "completed",
    }:
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
