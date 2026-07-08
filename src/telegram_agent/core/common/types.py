from enum import StrEnum


class TelegramAttachmentType(StrEnum):
    VOICE = "voice"
    VIDEO = "video"
    VIDEO_NOTE = "video_note"
    DOCUMENT = "document"
    AUDIO = "audio"
    PHOTO = "photo"
