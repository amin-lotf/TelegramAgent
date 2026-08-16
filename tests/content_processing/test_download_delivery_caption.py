from __future__ import annotations

from telegram_agent.core.content_processing.services.download_delivery_caption import (
    build_download_delivery_caption,
)


def test_video_caption_variants() -> None:
    assert (
        build_download_delivery_caption(
            media_type="video",
            requested_dub_language="English",
        )
        == "Video with English dub"
    )
    assert (
        build_download_delivery_caption(
            media_type="video",
            requested_subtitle_language="English",
        )
        == "Video with English subtitles"
    )
    assert (
        build_download_delivery_caption(
            media_type="video",
            requested_dub_language="English",
            requested_subtitle_language="Spanish",
        )
        == "Video with English dub and Spanish subtitles"
    )
    assert build_download_delivery_caption(media_type="video") == "Here is your video"


def test_audio_and_document_captions() -> None:
    assert (
        build_download_delivery_caption(
            media_type="audio",
            requested_language="French",
        )
        == "Audio in French"
    )
    assert build_download_delivery_caption(media_type="audio") == "Here is your audio"
    assert (
        build_download_delivery_caption(
            media_type="document",
            requested_format="pdf",
        )
        == "Here is your document (pdf)"
    )
    assert (
        build_download_delivery_caption(
            media_type="document",
            requested_subtitle_language="en",
        )
        == "Video with en subtitles"
    )
