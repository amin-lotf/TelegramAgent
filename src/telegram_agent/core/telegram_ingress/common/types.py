from enum import StrEnum


class AttachmentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class TelegramAttachmentType(StrEnum):
    VOICE = "voice"
    VIDEO = "video"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    AUDIO = "audio"
    PHOTO = "photo"