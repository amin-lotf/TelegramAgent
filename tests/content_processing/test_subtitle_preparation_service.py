from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from telegram_agent.core.common.exceptions import PermanentContentProcessingError
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitlePreparationService,
    SubtitleSegment,
)


def test_prepare_writes_valid_srt(tmp_path: Path) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    job_id = uuid4()
    segments = [
        SubtitleSegment(start_ms=0, end_ms=1500, text="Hello world"),
        SubtitleSegment(start_ms=2000, end_ms=3500, text="Second line"),
    ]

    path = service.prepare(job_id=job_id, segments=segments, target_language="en")

    output = Path(path)
    assert output.is_file()
    assert output.parent == tmp_path / str(job_id)
    content = output.read_text(encoding="utf-8")
    assert "Hello world" in content
    assert "Second line" in content
    assert "00:00:00,000 --> 00:00:01,500" in content


def test_prepare_reflows_long_whisper_segment_to_mobile_safe_cues(
    tmp_path: Path,
) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    long_text = (
        "In this demo, we want to test whether TalkToPDF can answer questions "
        "that are not asked with the exact same words from the document."
    )
    segments = [
        SubtitleSegment(start_ms=1168, end_ms=7597, text=long_text),
    ]

    path = service.prepare(job_id=uuid4(), segments=segments, target_language="en")
    content = Path(path).read_text(encoding="utf-8")
    blocks = [block for block in content.strip().split("\n\n") if block.strip()]

    # Long sentence must become more than one cue.
    assert len(blocks) >= 2

    for block in blocks:
        lines = block.split("\n")
        text_lines = lines[2:]
        assert 1 <= len(text_lines) <= 2
        for line in text_lines:
            assert len(line) <= 37


def test_prepare_skips_empty_segments_and_keeps_sequential_indices(
    tmp_path: Path,
) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    segments = [
        SubtitleSegment(start_ms=0, end_ms=1000, text="  "),
        SubtitleSegment(start_ms=1000, end_ms=2000, text="Keep me"),
    ]

    path = service.prepare(job_id=uuid4(), segments=segments, target_language=None)
    content = Path(path).read_text(encoding="utf-8")
    assert content.startswith("1\n")
    assert "Keep me" in content
    assert "2\n" not in content


def test_prepare_rejects_empty_segment_list(tmp_path: Path) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    with pytest.raises(PermanentContentProcessingError, match="without transcript"):
        service.prepare(job_id=uuid4(), segments=[], target_language=None)
