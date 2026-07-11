from enum import StrEnum


class JobKind(StrEnum):
    TELEGRAM_ATTACHMENT="telegram attachment"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"