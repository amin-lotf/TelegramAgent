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


