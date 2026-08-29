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
    CANCEL_ALL_SECONDARY_TASKS_REQUESTED = (
        "telegram_ingress.secondary_tasks.cancel_all.requested"
    )


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"

