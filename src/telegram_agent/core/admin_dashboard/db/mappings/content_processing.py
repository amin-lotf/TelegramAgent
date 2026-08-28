"""Read-only table mappings for content-processing."""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

jobs = Table(
    "jobs",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("error_message", Text, nullable=True),
    Column("callback_required", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

telegram_sources = Table(
    "telegram_sources",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("ingress_message_id", UUID(as_uuid=True), nullable=False),
    Column("ingress_attachment_id", UUID(as_uuid=True), nullable=False),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("telegram_file_id", String(512), nullable=False),
    Column("telegram_file_unique_id", String(255), nullable=True),
    Column("attachment_type", String(32), nullable=False),
)

media_assets = Table(
    "media_assets",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("role", String(32), nullable=False),
    Column("parent_asset_id", UUID(as_uuid=True), nullable=True),
    Column("local_path", Text, nullable=True),
    Column("media_type", String(32), nullable=False),
    Column("mime_type", String(128), nullable=True),
    Column("duration_ms", Integer, nullable=True),
    Column("size_bytes", BigInteger, nullable=True),
)

outbox_events = Table(
    "outbox_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("event_type", String(128), nullable=False),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(255), nullable=True),
    Column("last_error", Text, nullable=True),
)

transcripts = Table(
    "transcripts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("text", Text, nullable=False),
    Column("language", String(32), nullable=True),
    Column("language_probability", Float, nullable=True),
    Column("duration_ms", Integer, nullable=True),
)

download_requests = Table(
    "download_requests",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("group_id", UUID(as_uuid=True), nullable=False),
    Column("agent_message_id", UUID(as_uuid=True), nullable=False),
    Column("media_ingress_message_id", UUID(as_uuid=True), nullable=False),
    Column("media_type", String(32), nullable=False),
    Column("requested_subtitle_language", String(64), nullable=True),
    Column("requested_dub_language", String(64), nullable=True),
    Column("requested_language", String(64), nullable=True),
    Column("requested_format", String(64), nullable=True),
    Column("assistant_text", Text, nullable=True),
    Column("final_path", Text, nullable=True),
    Column("delivery_status", String(32), nullable=False),
    Column("delivery_attempt_count", Integer, nullable=False),
    Column("delivery_error", Text, nullable=True),
    Column("reply_to_message_id", BigInteger, nullable=True),
    Column("delivered_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

subtitle_translations = Table(
    "subtitle_translations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("source_language", String(32), nullable=True),
    Column("target_language", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("model_name", String(128), nullable=True),
    Column("error_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

translation_batches = Table(
    "translation_batches",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("subtitle_translation_id", UUID(as_uuid=True), nullable=False),
    Column("batch_index", Integer, nullable=False),
    Column("start_segment_index", Integer, nullable=False),
    Column("end_segment_index", Integer, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("last_error", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

dubbing_workflows = Table(
    "dubbing_workflows",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("source_job_id", UUID(as_uuid=True), nullable=False),
    Column("target_language", String(64), nullable=False),
    Column("status", String(32), nullable=False),
    Column("active_gpu_job_id", UUID(as_uuid=True), nullable=True),
    Column("cosyvoice_model", String(255), nullable=False),
    Column("sam_model", String(255), nullable=False),
    Column("error_message", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

transcript_segments = Table(
    "transcript_segments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("transcript_id", UUID(as_uuid=True), nullable=False),
    Column("segment_index", Integer, nullable=False),
    Column("start_ms", Integer, nullable=False),
    Column("end_ms", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("language", String(32), nullable=True),
    Column("language_probability", Float, nullable=True),
    Column("speaker", String(64), nullable=True),
    Column("speaker_confidence", Float, nullable=True),
)
