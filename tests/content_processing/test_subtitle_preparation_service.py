from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from telegram_agent.core.common.exceptions import PermanentContentProcessingError
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitlePreparationService,
    SubtitleSegment,
    _display_width,
    _format_rtl_srt_line,
)

_RLE = "\u202B"
_PDF = "\u202C"
_ALM = "\u061C"
_RLM = "\u200F"


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
            assert _display_width(line) <= 37


def test_prepare_reflows_long_chinese_to_short_cjk_lines(tmp_path: Path) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    long_text = (
        "这是一段很长的中文字幕用于测试换行是否会超出画面范围"
        "我们需要把它拆成多行以免字幕画到画面外面去"
    )
    path = service.prepare(
        job_id=uuid4(),
        segments=[SubtitleSegment(start_ms=0, end_ms=8000, text=long_text)],
        target_language="zh",
    )
    content = Path(path).read_text(encoding="utf-8")
    blocks = [block for block in content.strip().split("\n\n") if block.strip()]
    assert len(blocks) >= 2
    for block in blocks:
        text_lines = block.split("\n")[2:]
        assert 1 <= len(text_lines) <= 2
        for line in text_lines:
            assert _display_width(line) <= 37
            han = [char for char in line if "\u4e00" <= char <= "\u9fff"]
            assert len(han) <= 18


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


def test_persian_line_ending_with_period_and_question_mark() -> None:
    period_line = "و حالا من، ببخشید، ببخشید."
    assert _format_rtl_srt_line(period_line) == f"{_RLE}{period_line}{_ALM}{_PDF}"

    question_line = "خوبی؟"
    assert _format_rtl_srt_line(question_line) == f"{_RLE}{question_line}{_ALM}{_PDF}"

    latin_question = _format_rtl_srt_line("خوبی?")
    assert latin_question.endswith(f"؟{_ALM}{_PDF}")
    assert "?" not in latin_question


def test_two_line_persian_cue_wraps_each_text_line_only(tmp_path: Path) -> None:
    service = SubtitlePreparationService(storage_root=tmp_path)
    line1 = "سلام دنیا."
    line2 = "حالت چطوره؟"
    srt = service._render_srt(
        [
            SubtitleSegment(
                start_ms=0,
                end_ms=1500,
                text=f"{line1}\n{line2}",
            )
        ]
    )
    lines = srt.strip().split("\n")
    assert lines[0] == "1"
    assert lines[1] == "00:00:00,000 --> 00:00:01,500"
    assert lines[2] == f"{_RLE}{line1}{_ALM}{_PDF}"
    assert lines[3] == f"{_RLE}{line2}{_ALM}{_PDF}"
    assert _RLE not in lines[0]
    assert _RLE not in lines[1]
    assert _ALM not in lines[0]
    assert _ALM not in lines[1]
    assert _PDF not in lines[0]
    assert _PDF not in lines[1]


def test_english_cue_is_untouched(tmp_path: Path) -> None:
    assert _format_rtl_srt_line("Hello world.") == "Hello world."
    assert _format_rtl_srt_line("Hello, world?") == "Hello, world?"

    service = SubtitlePreparationService(storage_root=tmp_path)
    srt = service._render_srt(
        [SubtitleSegment(start_ms=0, end_ms=1000, text="Hello, world?")]
    )
    assert "Hello, world?" in srt
    assert _RLE not in srt
    assert _ALM not in srt
    assert _PDF not in srt


def test_existing_rle_rlm_does_not_double_wrap() -> None:
    formatted = _format_rtl_srt_line(f"{_RLE}اینجا.{_PDF}")
    assert formatted == f"{_RLE}اینجا.{_ALM}{_PDF}"
    assert formatted.count(_RLE) == 1
    assert formatted.count(_PDF) == 1
    assert formatted.count(_ALM) == 1

    with_rlm = _format_rtl_srt_line(f"{_RLM}اینجا.")
    assert with_rlm == f"{_RLE}اینجا.{_ALM}{_PDF}"
    assert _RLM not in with_rlm
    assert with_rlm.count(_RLE) == 1


def test_latin_punctuation_next_to_persian_is_localized() -> None:
    formatted = _format_rtl_srt_line("سلام, خوب; هستی?")
    assert formatted == f"{_RLE}سلام، خوب؛ هستی؟{_ALM}{_PDF}"
    assert "." in _format_rtl_srt_line("تمام.")
