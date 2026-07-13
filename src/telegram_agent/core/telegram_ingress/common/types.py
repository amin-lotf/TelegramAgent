from enum import StrEnum


class AttachmentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class ConversationStatus(StrEnum):
    PENDING = "pending"
    ENQUEUED = "enqueued"
    DISPATCHED = "dispatched"
    FAILED = "failed"


class OutboxEventType(StrEnum):
    CONVERSATION_MESSAGES_ENQUEUED = "telegram_ingress.conversation_messages.enqueued"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


