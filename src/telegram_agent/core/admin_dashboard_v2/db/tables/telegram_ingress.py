from sqlalchemy import BigInteger, Column, DateTime, Integer, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID


metadata = MetaData()

user_messages = Table(
    "user_messages",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("telegram_user_id", BigInteger, nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("message_id", BigInteger, nullable=False),
    Column("update_id", BigInteger),
    Column("reply_message_id", BigInteger),
    Column("text", Text),
    Column("conversation_status", String(32), nullable=False),
    Column("dispatch_event_id", UUID(as_uuid=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

attachments = Table(
    "attachments",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("user_message_id", UUID(as_uuid=True), nullable=False),
    Column("file_id", String(512), nullable=False),
    Column("file_unique_id", String(255)),
    Column("type", String(32), nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

conversation_outbox_events = Table(
    "conversation_outbox_events",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True),
    Column("event_type", String(128), nullable=False),
    Column("chat_id", BigInteger, nullable=False),
    Column("first_message_id", BigInteger, nullable=False),
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
