"""Application view models for list and message-trace pages (not source of truth)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from telegram_agent.core.admin_dashboard.common.types import (
    DbAvailability,
    DbName,
    OverallState,
    StageKey,
    StageStatus,
)


@dataclass(frozen=True, slots=True)
class AttachmentRow:
    id: UUID
    user_message_id: UUID
    file_id: str
    file_unique_id: str | None
    type: str
    status: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxRow:
    id: UUID
    event_type: str
    status: str
    attempt_count: int
    created_at: datetime
    published_at: datetime | None
    available_at: datetime
    locked_at: datetime | None
    locked_by: str | None
    last_error: str | None
    idempotency_key: str
    payload: dict[str, Any]
    # service-specific optional columns
    chat_id: int | None = None
    first_message_id: int | None = None
    job_id: UUID | None = None
    runtime_message_id: UUID | None = None
    message_id: int | None = None


@dataclass(frozen=True, slots=True)
class UserMessageRow:
    id: UUID
    telegram_user_id: int
    chat_id: int
    message_id: int
    update_id: int | None
    reply_message_id: int | None
    text: str | None
    conversation_status: str
    dispatch_event_id: UUID | None
    created_at: datetime
    attachment: AttachmentRow | None = None


@dataclass(frozen=True, slots=True)
class JobRow:
    id: UUID
    kind: str
    status: str
    idempotency_key: str
    error_message: str | None
    callback_required: bool
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TelegramSourceRow:
    id: UUID
    job_id: UUID
    ingress_message_id: UUID
    ingress_attachment_id: UUID
    telegram_user_id: int
    telegram_file_id: str
    telegram_file_unique_id: str | None
    attachment_type: str


@dataclass(frozen=True, slots=True)
class MediaAssetRow:
    id: UUID
    job_id: UUID
    role: str
    parent_asset_id: UUID | None
    local_path: str | None
    media_type: str
    mime_type: str | None
    duration_ms: int | None
    size_bytes: int | None


@dataclass(frozen=True, slots=True)
class TranscriptSegmentRow:
    id: UUID
    transcript_id: UUID
    segment_index: int
    start_ms: int
    end_ms: int
    text: str
    language: str | None
    language_probability: float | None
    speaker: str | None
    speaker_confidence: float | None


@dataclass(frozen=True, slots=True)
class TranscriptRow:
    id: UUID
    job_id: UUID
    text: str
    language: str | None
    language_probability: float | None
    duration_ms: int | None
    segments: tuple[TranscriptSegmentRow, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeBatchRow:
    id: UUID
    chat_id: int
    idempotency_key: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationGroupRow:
    id: UUID
    chat_id: int
    group_number: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeMessageRow:
    id: UUID
    batch_id: UUID
    ingress_message_id: UUID
    chat_id: int
    telegram_user_id: int
    message_id: int
    reply_message_id: int | None
    text: str | None
    attachment_ingress_id: UUID | None
    attachment_type: str | None
    attachment_status: str | None
    attachment_file_id: str | None
    attachment_file_unique_id: str | None
    group_id: UUID | None
    coordination_status: str
    coordinated_at: datetime | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ConversationClaimRow:
    chat_id: int
    status: str
    claim_token: UUID | None
    locked_at: datetime | None
    locked_by: str | None
    available_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AuthUserRow:
    id: int
    telegram_user_id: int
    chat_id: int
    username: str | None
    first_name: str | None
    last_name: str | None
    is_active: bool
    last_seen_at: datetime


@dataclass(frozen=True, slots=True)
class FailureInfo:
    source: str
    message: str
    status: str | None = None


@dataclass(frozen=True, slots=True)
class TimelineEvent:
    key: StageKey
    label: str
    status: StageStatus
    timestamp: datetime | None
    detail: str | None = None
    source_db: DbName | None = None


@dataclass(frozen=True, slots=True)
class ContentProcessingView:
    job: JobRow | None
    source: TelegramSourceRow | None
    assets: tuple[MediaAssetRow, ...] = ()
    outbox_events: tuple[OutboxRow, ...] = ()
    transcript: TranscriptRow | None = None
    not_applicable: bool = False


@dataclass(frozen=True, slots=True)
class AgentRuntimeView:
    message: RuntimeMessageRow | None
    batch: RuntimeBatchRow | None
    group: ConversationGroupRow | None
    outbox: OutboxRow | None
    claim: ConversationClaimRow | None


@dataclass(frozen=True, slots=True)
class MessageListItem:
    id: UUID
    created_at: datetime
    chat_id: int
    telegram_user_id: int
    message_id: int
    text_preview: str
    conversation_status: str
    has_attachment: bool
    attachment_type: str | None
    attachment_status: str | None
    overall_state: OverallState
    overall_state_label: str


@dataclass(frozen=True, slots=True)
class MessageListResult:
    items: tuple[MessageListItem, ...]
    total: int
    page: int
    page_size: int
    ingress_availability: DbAvailability
    secondary_availability: dict[DbName, DbAvailability] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MessageTrace:
    found: bool
    ingress_message_id: UUID | None
    overall_state: OverallState
    overall_state_label: str
    ingress: UserMessageRow | None
    ingress_outbox: OutboxRow | None
    content_processing: ContentProcessingView | None
    agent_runtime: AgentRuntimeView | None
    auth_user: AuthUserRow | None
    timeline: tuple[TimelineEvent, ...]
    failures: tuple[FailureInfo, ...]
    db_availability: dict[DbName, DbAvailability]
    text_preview: str = ""
