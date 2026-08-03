from sqlalchemy import BigInteger, Boolean, Column, DateTime, Float, Integer, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID


metadata = MetaData()

jobs = Table(
    "jobs", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("kind", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("error_message", Text),
    Column("callback_required", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

telegram_sources = Table(
    "telegram_sources", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("ingress_message_id", UUID(as_uuid=True), nullable=False),
    Column("ingress_attachment_id", UUID(as_uuid=True), nullable=False),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("telegram_file_id", String(512), nullable=False),
    Column("telegram_file_unique_id", String(255)),
    Column("attachment_type", String(32), nullable=False),
)

media_assets = Table(
    "media_assets", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("role", String(32), nullable=False),
    Column("parent_asset_id", UUID(as_uuid=True)),
    Column("local_path", Text),
    Column("media_type", String(32), nullable=False),
    Column("mime_type", String(128)),
    Column("duration_ms", Integer),
    Column("size_bytes", BigInteger),
)

outbox_events = Table(
    "outbox_events", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("event_type", String(128), nullable=False),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", String(32), nullable=False),
    Column("attempt_count", Integer, nullable=False),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("locked_at", DateTime(timezone=True)),
    Column("locked_by", String(255)),
    Column("last_error", Text),
)

transcripts = Table(
    "transcripts", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("job_id", UUID(as_uuid=True), nullable=False),
    Column("text", Text, nullable=False),
    Column("language", String(32)),
    Column("language_probability", Float),
    Column("duration_ms", Integer),
)

transcript_segments = Table(
    "transcript_segments", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("transcript_id", UUID(as_uuid=True), nullable=False),
    Column("segment_index", Integer, nullable=False),
    Column("start_ms", Integer, nullable=False),
    Column("end_ms", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("language", String(32)),
    Column("language_probability", Float),
    Column("speaker", String(64)),
    Column("speaker_confidence", Float),
    Column("emotion", String(64)),
    Column("audio_events", JSONB),
)
