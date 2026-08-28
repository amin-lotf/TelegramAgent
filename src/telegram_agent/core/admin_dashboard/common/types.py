"""Enums and shared type aliases for the admin dashboard view model."""
from __future__ import annotations

from enum import StrEnum


class DbName(StrEnum):
    INGRESS = "ingress"
    CONTENT_PROCESSING = "content_processing"
    AGENT_RUNTIME = "agent_runtime"
    AUTH = "auth"


class DbAvailability(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    SKIPPED = "skipped"


class OverallState(StrEnum):
    FAILED = "failed"
    WAITING_MEDIA = "waiting_media"
    PROCESSING_MEDIA = "processing_media"
    DISPATCHING = "dispatching"
    COORDINATING = "coordinating"
    CLASSIFYING = "classifying"
    HANDLING_DOWNLOAD = "handling_download"
    COMPLETED = "completed"
    PENDING_DISPATCH = "pending_dispatch"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class StageKey(StrEnum):
    MESSAGE_RECEIVED = "message_received"
    ATTACHMENT_REGISTERED = "attachment_registered"
    CP_JOB_CREATED = "cp_job_created"
    MEDIA_DOWNLOADED = "media_downloaded"
    MEDIA_DEMUXED = "media_demuxed"
    TRANSCRIPTION_DONE = "transcription_done"
    CP_FINISHED = "cp_finished"
    ATTACHMENT_RESULT_APPLIED = "attachment_result_applied"
    CONVERSATION_ENQUEUED = "conversation_enqueued"
    CONVERSATION_DISPATCHED = "conversation_dispatched"
    RUNTIME_INGESTED = "runtime_ingested"
    COORDINATED = "coordinated"
    INTENT_CLASSIFIED = "intent_classified"
    DOWNLOAD_HANDLED = "download_handled"
    CONTENT_PROCESSING_HANDOFF = "content_processing_handoff"
    DUBBING = "dubbing"


class StageStatus(StrEnum):
    COMPLETED = "completed"
    PENDING = "pending"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NOT_STARTED = "not_started"
    NOT_APPLICABLE = "not_applicable"
    UNAVAILABLE = "unavailable"


class WorkflowState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"
