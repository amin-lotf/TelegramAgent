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
from pgvector.sqlalchemy import Vector

from telegram_agent.core.content_processing.common.const import (
    DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
)

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

content_chunks = Table(
    "content_chunks",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("content_type", String(32), nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("start_ms", Integer, nullable=True),
    Column("end_ms", Integer, nullable=True),
    Column("char_count", Integer, nullable=False),
    Column("token_count", Integer, nullable=True),
    Column("segment_index_start", Integer, nullable=True),
    Column("segment_index_end", Integer, nullable=True),
    Column("speakers", JSONB, nullable=True),
    Column("strategy", String(128), nullable=False),
    Column("metadata", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

chunk_embeddings = Table(
    "chunk_embeddings",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("chunk_id", UUID(as_uuid=True), nullable=False),
    Column("provider", String(64), nullable=False),
    Column("model", String(128), nullable=False),
    Column("dimensions", Integer, nullable=False),
    Column("embedding", Vector(DEFAULT_EMBEDDING_VECTOR_DIMENSIONS), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
