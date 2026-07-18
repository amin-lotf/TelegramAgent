"""Read-only table mappings for agent-runtime."""
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

metadata = MetaData()

runtime_batches = Table(
    "runtime_batches",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("chat_id", BigInteger, nullable=False),
    Column("idempotency_key", String(255), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

conversation_groups = Table(
    "conversation_groups",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("chat_id", BigInteger, nullable=False),
    Column("group_number", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

runtime_messages = Table(
    "runtime_messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("batch_id", UUID(as_uuid=True), nullable=False),
    Column("ingress_message_id", UUID(as_uuid=True), nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("message_id", BigInteger, nullable=False),
    Column("reply_message_id", BigInteger, nullable=True),
    Column("text", Text, nullable=True),
    Column("attachment_ingress_id", UUID(as_uuid=True), nullable=True),
    Column("attachment_type", String(32), nullable=True),
    Column("attachment_status", String(32), nullable=True),
    Column("attachment_file_id", String(512), nullable=True),
    Column("attachment_file_unique_id", String(255), nullable=True),
    Column("group_id", UUID(as_uuid=True), nullable=True),
    Column("coordination_status", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("intent", String(32), nullable=True),
    Column("coordinated_at", DateTime(timezone=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

conversation_claims = Table(
    "conversation_claims",
    metadata,
    Column("chat_id", BigInteger, primary_key=True),
    Column("status", String(32), nullable=False),
    Column("claim_token", UUID(as_uuid=True), nullable=True),
    Column("locked_at", DateTime(timezone=True), nullable=True),
    Column("locked_by", String(255), nullable=True),
    Column("available_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

coordination_outbox_events = Table(
    "coordination_outbox_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("event_type", String(128), nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("runtime_message_id", UUID(as_uuid=True), nullable=False),
    Column("message_id", BigInteger, nullable=False),
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
