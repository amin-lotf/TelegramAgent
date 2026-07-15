from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import Any, Generic, TypeVar
from uuid import UUID


class DataSourceStatus(StrEnum):
    AVAILABLE = "available"
    RECORD_NOT_FOUND = "record_not_found"
    UNAVAILABLE = "unavailable"
    TIMED_OUT = "timed_out"
    INVALID_SCHEMA = "invalid_schema"
    NOT_CONFIGURED = "not_configured"


class StageStatus(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    NOT_STARTED = "not_started"
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    UNKNOWN = "unknown"
    NOT_IMPLEMENTED = "not_implemented"


T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SourceResult(Generic[T]):
    source: str
    status: DataSourceStatus
    data: T | None = None
    message: str | None = None

    @property
    def available(self) -> bool:
        return self.status in {
            DataSourceStatus.AVAILABLE,
            DataSourceStatus.RECORD_NOT_FOUND,
        }


@dataclass(frozen=True, slots=True)
class MessageListFilters:
    chat_id: int | None = None
    message_id: int | None = None
    update_id: int | None = None
    telegram_user_id: int | None = None
    ingress_message_id: UUID | None = None
    runtime_group_id: UUID | None = None
    content_job_id: UUID | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    ingress_status: str | None = None
    attachment_status: str | None = None
    attachment_type: str | None = None
    has_attachment: bool | None = None
    content_status: str | None = None
    runtime_status: str | None = None
    failed_only: bool = False

    @property
    def has_cross_service_filter(self) -> bool:
        return bool(
            self.runtime_group_id
            or self.content_job_id
            or self.content_status
            or self.runtime_status
            or self.failed_only
        )

    def fingerprint_values(self) -> dict[str, object]:
        return {
            key: (
                value.isoformat()
                if isinstance(value, datetime)
                else str(value)
                if isinstance(value, UUID)
                else value
            )
            for item in fields(self)
            for key, value in ((item.name, getattr(self, item.name)),)
        }


@dataclass(frozen=True, slots=True)
class CursorPosition:
    created_at: datetime
    message_id: UUID


@dataclass(frozen=True, slots=True)
class MessageSummaryView:
    ingress_message_id: UUID
    telegram_user_id: int
    chat_id: int
    message_id: int
    update_id: int | None
    text_preview: str
    created_at: datetime
    conversation_status: str
    attachment_type: str | None
    attachment_status: str | None
    current_user_label: str | None
    content_statuses: tuple[str, ...]
    runtime_status: str | None
    overall_status: str
    has_failure: bool
    has_pending: bool
    has_partial_data: bool


@dataclass(frozen=True, slots=True)
class MessagePageView:
    items: tuple[MessageSummaryView, ...]
    next_cursor: str | None
    scanned_count: int
    scan_limit_reached: bool
    source_states: tuple[SourceResult[None], ...] = ()


@dataclass(frozen=True, slots=True)
class TimelineEventView:
    key: str
    service: str
    label: str
    status: StageStatus
    timestamp: datetime | None
    detail: str | None = None
    record_id: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleStageView:
    key: str
    label: str
    service: str
    status: StageStatus
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class MessageTraceView:
    ingress_message_id: UUID
    ingress: SourceResult[dict[str, Any]]
    content_processing: SourceResult[dict[str, Any]]
    agent_runtime: SourceResult[dict[str, Any]]
    telegram_auth: SourceResult[dict[str, Any]]
    lifecycle: tuple[LifecycleStageView, ...]
    timeline: tuple[TimelineEventView, ...]
    overall_status: str
    failures: tuple[dict[str, str], ...] = ()
    warnings: tuple[str, ...] = ()
    available_tabs: tuple[str, ...] = field(default_factory=tuple)
