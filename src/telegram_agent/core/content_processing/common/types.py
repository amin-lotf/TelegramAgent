from enum import StrEnum


class JobKind(StrEnum):
    VIDEO = "video"
    WEB = "web"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"