from __future__ import annotations

from pathlib import Path

from telegram_agent.core.content_processing.downloaders.media_container import (
    is_opaque_suffix,
    path_looks_like_video,
    sniff_media_container,
)


def test_sniff_matroska_header(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    # EBML magic used by MKV/WebM.
    path.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 32)
    info = sniff_media_container(path)
    assert info is not None
    assert info.suffix == ".mkv"
    assert info.is_video is True
    assert path_looks_like_video(path) is True


def test_sniff_mp4_ftyp(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16)
    info = sniff_media_container(path)
    assert info is not None
    assert info.suffix == ".mp4"
    assert info.is_video is True


def test_opaque_suffix_detection() -> None:
    assert is_opaque_suffix(".bin") is True
    assert is_opaque_suffix(".mkv") is False
    assert is_opaque_suffix("") is True
