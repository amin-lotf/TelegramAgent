from __future__ import annotations

import json
from dataclasses import dataclass

from telegram_agent.core.common.types import TelegramAttachmentType

_VIDEO_SYSTEM_PROMPT = """Decide if the user wants a download/processing action for a video attachment.

Return only structured fields:
- is_download_request: true only when the user clearly asks to download/process the video (e.g. subtitles, dub, language, prepare/download/convert). false for chitchat, off-topic, empty, or too vague requests.
- requested_subtitle_language: language code/name for subtitles, or null if unspecified or is_download_request is false
- requested_dub_language: language code/name for dubbing/audio track, or null if unspecified or is_download_request is false
- assistant_text: short user-facing status text only. If is_download_request is true, confirm that preparation has started (e.g. "Preparing the video with English dub."). This is sent immediately as a chat reply while work runs — it is NOT the final media caption. If false, a short polite explanation that you only handle download-related media requests and why this message was not acted on.

Do not invent languages the user did not ask for. Keep assistant_text concise. When is_download_request is false, set language fields to null."""

_AUDIO_SYSTEM_PROMPT = """Decide if the user wants a download/processing action for an audio attachment.

Return only structured fields:
- is_download_request: true only when the user clearly asks to download/process the audio (e.g. language, transcribe, prepare/download/convert). false for chitchat, off-topic, empty, or too vague requests.
- requested_language: language code/name if the user requested a language, else null (always null when is_download_request is false)
- assistant_text: short user-facing status text only. If is_download_request is true, confirm that preparation has started (e.g. "Preparing your audio."). This is sent immediately as a chat reply while work runs — it is NOT the final media caption. If false, a short polite explanation that you only handle download-related media requests and why this message was not acted on.

Do not invent languages the user did not ask for. Keep assistant_text concise. When is_download_request is false, set requested_language to null."""

_DOCUMENT_SYSTEM_PROMPT = """Decide if the user wants a download/processing action for a document attachment.
Telegram often delivers video files (especially MKV) as documents.

Return only structured fields:
- is_download_request: true only when the user clearly asks to download/process the file (e.g. subtitles, dub, format, translation, prepare/download/convert). false for chitchat, off-topic, empty, or too vague requests.
- requested_subtitle_language: language code/name for subtitles/translation, or null if unspecified or is_download_request is false
- requested_dub_language: language code/name for dubbing/audio track, or null if unspecified or is_download_request is false
- requested_format: preferred container/format if the user requested one, else null (always null when is_download_request is false)
- assistant_text: short user-facing status text only. If is_download_request is true, confirm that preparation has started (e.g. "Preparing your file with English subtitles."). This is sent immediately as a chat reply while work runs — it is NOT the final media caption. If false, a short polite explanation that you only handle download-related media requests and why this message was not acted on.

Do not invent languages or formats the user did not ask for. Keep assistant_text concise.
If the user asks for translation or subtitles, populate requested_subtitle_language.
When is_download_request is false, set all extraction fields to null."""


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
