"""Derive overall operational state from multi-service records."""
from __future__ import annotations

from telegram_agent.core.admin_dashboard.common.types import OverallState
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    ContentProcessingView,
    UserMessageRow,
)

_BLOCKING_ATTACHMENT_TYPES = frozenset({"voice", "video_note"})
_TERMINAL_ATTACHMENT = frozenset({"ready", "failed"})
_ACTIVE_JOB = frozenset({"queued", "running", "downloaded", "transcribing"})
_FAILED_JOB = frozenset({"failed", "cancelled", "timed_out"})
_PIPELINE_IN_PROGRESS = frozenset(
    {"received", "coordinating", "coordinated", "classifying"}
)


def overall_state_label(state: OverallState) -> str:
    return {
        OverallState.FAILED: "Failed",
        OverallState.WAITING_MEDIA: "Waiting for media",
        OverallState.PROCESSING_MEDIA: "Processing media",
        OverallState.DISPATCHING: "Dispatching",
        OverallState.COORDINATING: "Coordinating",
        OverallState.CLASSIFYING: "Classifying intent",
        OverallState.COMPLETED: "Completed",
        OverallState.PENDING_DISPATCH: "Pending dispatch",
        OverallState.PARTIAL: "Partial",
        OverallState.UNKNOWN: "Unknown",
    }[state]


def derive_overall_state(
    *,
    message: UserMessageRow | None,
    content: ContentProcessingView | None,
    runtime: AgentRuntimeView | None,
) -> OverallState:
    if message is None:
        return OverallState.UNKNOWN

    attachment = message.attachment
    job = content.job if content is not None else None
    runtime_message = runtime.message if runtime is not None else None
    outbox_events = ()
    if runtime is not None:
        if runtime.outbox_events:
            outbox_events = runtime.outbox_events
        elif runtime.outbox is not None:
            outbox_events = (runtime.outbox,)

    if message.conversation_status == "failed":
        return OverallState.FAILED
    if attachment is not None and attachment.status == "failed":
        return OverallState.FAILED
    if job is not None and job.status in _FAILED_JOB:
        return OverallState.FAILED
    if any(event.status == "failed" for event in outbox_events):
        return OverallState.FAILED
    if runtime_message is not None and runtime_message.status == "failed":
        return OverallState.FAILED

    if (
        attachment is not None
        and attachment.type in _BLOCKING_ATTACHMENT_TYPES
        and attachment.status not in _TERMINAL_ATTACHMENT
        and message.conversation_status == "pending"
    ):
        return OverallState.WAITING_MEDIA

    if job is not None and job.status in _ACTIVE_JOB:
        return OverallState.PROCESSING_MEDIA

    if message.conversation_status == "enqueued":
        return OverallState.DISPATCHING

    if message.conversation_status == "dispatched" and runtime_message is not None:
        pipeline = runtime_message.status
        if pipeline == "classified":
            return OverallState.COMPLETED
        if pipeline in {"coordinated", "classifying"}:
            return OverallState.CLASSIFYING
        if pipeline in {"received", "coordinating"}:
            return OverallState.COORDINATING
        # Fallback when only coordination_status is known (list enrichment).
        if runtime_message.coordination_status == "pending":
            return OverallState.COORDINATING
        if runtime_message.coordination_status in {"grouped", "vague"}:
            return OverallState.COMPLETED

    if message.conversation_status == "pending":
        return OverallState.PENDING_DISPATCH

    if message.conversation_status == "dispatched" and runtime_message is None:
        return OverallState.PARTIAL

    return OverallState.PARTIAL
