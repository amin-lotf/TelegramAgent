from __future__ import annotations

import json
from dataclasses import dataclass

from telegram_agent.core.common.types import TelegramAttachmentType

_VIDEO_SYSTEM_PROMPT = """Extract a download request for a video attachment.
Return only structured fields:
- requested_subtitle_language: language code/name for subtitles, or null if unspecified
- requested_dub_language: language code/name for dubbing/audio track, or null if unspecified
- assistant_text: short user-facing confirmation that the request is being prepared

Do not invent languages the user did not ask for. Keep assistant_text concise."""

_AUDIO_SYSTEM_PROMPT = """Extract a download request for an audio attachment.
Return only structured fields:
- requested_language: language code/name if the user requested a language, else null
- assistant_text: short user-facing confirmation that the request is being prepared

Do not invent languages the user did not ask for. Keep assistant_text concise."""

_DOCUMENT_SYSTEM_PROMPT = """Extract a download request for a document attachment.
Telegram often delivers video files (especially MKV) as documents.
Return only structured fields:
- requested_subtitle_language: language code/name for subtitles/translation, or null if unspecified
- requested_dub_language: language code/name for dubbing/audio track, or null if unspecified
- requested_format: preferred container/format if the user requested one, else null
- assistant_text: short user-facing confirmation that the request is being prepared

Do not invent languages or formats the user did not ask for. Keep assistant_text concise.
If the user asks for translation or subtitles, populate requested_subtitle_language."""


@dataclass(frozen=True, slots=True)
class DownloadAgentPrompts:
    system_prompt: str
    user_prompt: str
    media_type: str


def build_download_agent_prompts(
    *,
    media_type: TelegramAttachmentType,
    group_texts: list[str],
    media_message_id: int,
) -> DownloadAgentPrompts:
    if media_type == TelegramAttachmentType.VIDEO:
        system_prompt = _VIDEO_SYSTEM_PROMPT
        media_type_value = "video"
    elif media_type == TelegramAttachmentType.AUDIO:
        system_prompt = _AUDIO_SYSTEM_PROMPT
        media_type_value = "audio"
    elif media_type == TelegramAttachmentType.DOCUMENT:
        system_prompt = _DOCUMENT_SYSTEM_PROMPT
        media_type_value = "document"
    else:
        raise ValueError(f"Unsupported download media type: {media_type}")

    prompt_data = {
        "media_type": media_type_value,
        "media_message_id": media_message_id,
        "user_texts": group_texts,
    }
    return DownloadAgentPrompts(
        system_prompt=system_prompt,
        user_prompt=json.dumps(
            prompt_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        media_type=media_type_value,
    )
