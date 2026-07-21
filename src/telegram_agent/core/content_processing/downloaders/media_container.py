"""Detect media container format from magic bytes.

Local Bot API often stores Telegram documents without a filename extension.
Saving those as ``.bin`` breaks ffmpeg remux and makes delivery look broken.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class MediaContainerInfo:
    """Result of sniffing a local media file."""

    suffix: str
    mime_type: str | None
    is_video: bool
    is_audio: bool


_OPAQUE_SUFFIXES = frozenset({".bin", ".dat", ".tmp", ".part", ""})

# Common video containers we demux/transcribe even when Telegram classifies
# the attachment as ``document`` (typical for MKV and large files).
_VIDEO_SUFFIXES = frozenset({".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi"})
_AUDIO_SUFFIXES = frozenset({".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".flac"})


def is_opaque_suffix(suffix: str) -> bool:
    return suffix.lower() in _OPAQUE_SUFFIXES


def is_video_suffix(suffix: str) -> bool:
    return suffix.lower() in _VIDEO_SUFFIXES


def is_audio_suffix(suffix: str) -> bool:
    return suffix.lower() in _AUDIO_SUFFIXES


def sniff_media_container(path: Path | str) -> MediaContainerInfo | None:
    """Return container info from file magic, or None if unrecognized."""
    file_path = Path(path)
    try:
        with file_path.open("rb") as handle:
            header = handle.read(64)
    except OSError:
        return None
    if len(header) < 12:
        return None

    # Matroska / WebM (EBML)
    if header.startswith(b"\x1a\x45\xdf\xa3"):
        # Prefer .mkv; both share EBML. Downstream demux treats them the same.
        if b"webm" in header[:64].lower():
            return MediaContainerInfo(
                suffix=".webm",
                mime_type="video/webm",
                is_video=True,
                is_audio=False,
            )
        return MediaContainerInfo(
            suffix=".mkv",
            mime_type="video/x-matroska",
            is_video=True,
            is_audio=False,
        )

    # ISO BMFF (MP4 / M4V / M4A / MOV)
    if len(header) >= 8 and header[4:8] == b"ftyp":
        brand = header[8:12]
        if brand in {b"M4A ", b"M4B "}:
            return MediaContainerInfo(
                suffix=".m4a",
                mime_type="audio/mp4",
                is_video=False,
                is_audio=True,
            )
        if brand == b"qt  ":
            return MediaContainerInfo(
                suffix=".mov",
                mime_type="video/quicktime",
                is_video=True,
                is_audio=False,
            )
        if brand == b"M4V ":
            return MediaContainerInfo(
                suffix=".m4v",
                mime_type="video/mp4",
                is_video=True,
                is_audio=False,
            )
        return MediaContainerInfo(
            suffix=".mp4",
            mime_type="video/mp4",
            is_video=True,
            is_audio=False,
        )

    # Ogg (often Opus/Vorbis from Telegram voice)
    if header.startswith(b"OggS"):
        return MediaContainerInfo(
            suffix=".ogg",
            mime_type="audio/ogg",
            is_video=False,
            is_audio=True,
        )

    # RIFF AVI / WAVE
    if header.startswith(b"RIFF") and len(header) >= 12:
        form = header[8:12]
        if form == b"AVI ":
            return MediaContainerInfo(
                suffix=".avi",
                mime_type="video/x-msvideo",
                is_video=True,
                is_audio=False,
            )
        if form == b"WAVE":
            return MediaContainerInfo(
                suffix=".wav",
                mime_type="audio/wav",
                is_video=False,
                is_audio=True,
            )

    # ID3 or MPEG audio frame
    if header.startswith(b"ID3") or header[:2] in {b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"\xff\xf2"}:
        return MediaContainerInfo(
            suffix=".mp3",
            mime_type="audio/mpeg",
            is_video=False,
            is_audio=True,
        )

    # FLAC
    if header.startswith(b"fLaC"):
        return MediaContainerInfo(
            suffix=".flac",
            mime_type="audio/flac",
            is_video=False,
            is_audio=True,
        )

    return None


def path_looks_like_video(path: Path | str) -> bool:
    """True if path suffix or magic indicates a demuxable video container."""
    file_path = Path(path)
    if is_video_suffix(file_path.suffix):
        return True
    info = sniff_media_container(file_path)
    return bool(info and info.is_video)


def path_looks_like_audio(path: Path | str) -> bool:
    """True if path suffix or magic indicates an audio container."""
    file_path = Path(path)
    if is_audio_suffix(file_path.suffix):
        return True
    info = sniff_media_container(file_path)
    return bool(info and info.is_audio)
