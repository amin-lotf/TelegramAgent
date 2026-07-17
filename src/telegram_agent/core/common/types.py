from enum import StrEnum


class AttachmentProcessingResultStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class TelegramAttachmentType(StrEnum):
    VOICE = "voice"
    VIDEO = "video"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    AUDIO = "audio"
    PHOTO = "photo"
