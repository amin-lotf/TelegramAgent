"""Deterministic delivery captions for prepared download media.

Status/preparing text from the download agent is sent as a separate reply while
work is in progress. Final media captions are built here from request fields so
the user never sees "preparing…" on the finished file.
"""

from __future__ import annotations


def build_download_delivery_caption(
    *,
    media_type: str,
    requested_subtitle_language: str | None = None,
    requested_dub_language: str | None = None,
    requested_language: str | None = None,
    requested_format: str | None = None,
) -> str:
    """Return a short caption describing the delivered media."""
    media = (media_type or "document").strip().lower()
    subtitle = _clean_label(requested_subtitle_language)
    dub = _clean_label(requested_dub_language)
    language = _clean_label(requested_language)
    fmt = _clean_label(requested_format)

    if media == "video" or media == "document":
        if dub and subtitle:
            return f"Video with {dub} dub and {subtitle} subtitles"
        if dub:
            return f"Video with {dub} dub"
        if subtitle:
            return f"Video with {subtitle} subtitles"
        if fmt and media == "document":
            return f"Here is your document ({fmt})"
        if media == "document":
            return "Here is your document"
        return "Here is your video"

    if media == "audio":
        if language:
            return f"Audio in {language}"
        return "Here is your audio"

    return "Here is your file"


def _clean_label(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
