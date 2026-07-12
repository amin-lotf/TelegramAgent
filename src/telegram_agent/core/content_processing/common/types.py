from enum import StrEnum


class JobKind(StrEnum):
    TELEGRAM_ATTACHMENT="telegram attachment"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutboxEventType(StrEnum):
    CONTENT_PROCESSING_JOB_READY = "content_processing.job.ready"
    MEDIA_READY_FOR_TRANSCRIPTION = "content_processing.media.ready_for_transcription"
    CONTENT_PROCESSING_JOB_FINISHED = "content_processing.job.finished"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
