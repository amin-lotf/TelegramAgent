from enum import StrEnum


class JobKind(StrEnum):
    TELEGRAM_ATTACHMENT = "telegram attachment"
    DOWNLOAD_PREPARATION = "download preparation"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DOWNLOADED = "downloaded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    CHUNKING = "chunking"
    CHUNKED = "chunked"
    EMBEDDING = "embedding"
    EMBEDDED = "embedded"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ContentChunkType(StrEnum):
    TRANSCRIPT = "transcript"


class DownloadMediaType(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"


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
    TRANSCRIPT_READY_FOR_CHUNKING = "content_processing.transcript.ready_for_chunking"
    CHUNKS_READY_FOR_EMBEDDING = "content_processing.chunks.ready_for_embedding"
    CONTENT_PROCESSING_JOB_FINISHED = "content_processing.job.finished"
    DOWNLOAD_PREPARATION_READY = "content_processing.download_preparation.ready"
    DOWNLOAD_READY_FOR_DELIVERY = "content_processing.download.ready_for_delivery"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


class SubtitleTranslationStatus(StrEnum):
    PENDING = "pending"
    BUILDING_GLOSSARY = "building_glossary"
    TRANSLATING = "translating"
    COMPLETED = "completed"
    FAILED = "failed"


class TranslationBatchStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
