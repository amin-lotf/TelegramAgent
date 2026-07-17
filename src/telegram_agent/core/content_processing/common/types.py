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
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class JobCompletionExpectationKind(StrEnum):
    JOB_COMPLETION = "job_completion"


class JobCompletionExpectationStatus(StrEnum):
    OPEN = "open"
    PROCESSING = "processing"
    SATISFIED = "satisfied"
    TIMED_OUT = "timed_out"


class MediaAssetRole(StrEnum):
    SOURCE = "source"
    AUDIO = "audio"
    VIDEO = "video"


class OutboxEventType(StrEnum):
    CONTENT_PROCESSING_JOB_READY = "content_processing.job.ready"
    MEDIA_READY_FOR_TRANSCRIPTION = "content_processing.media.ready_for_transcription"
    CONTENT_PROCESSING_JOB_FINISHED = "content_processing.job.finished"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"
