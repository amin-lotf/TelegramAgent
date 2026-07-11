from enum import StrEnum


class JobKind(StrEnum):
    TELEGRAM_ATTACHMENT="telegram attachment"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxEventType(StrEnum):
    CONTENT_PROCESSING_JOB_READY = "content_processing.job.ready"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
