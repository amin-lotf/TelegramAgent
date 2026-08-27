"""Tests for aligned-word WhisperX transcript segmentation."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from telegram_agent.core.whisperx.common.results import ModelTranscriptSegment
from telegram_agent.core.whisperx.common.settings import Settings
from telegram_agent.core.whisperx.runtime import WhisperXRuntime
from telegram_agent.core.whisperx.segmentation import (
    SegmentSizing,
    TranscriptSegmenter,
    merge_transcript_segments,
)


def _segmenter(
    *,
    target_duration: float = 7.0,
    min_duration: float = 2.0,
    max_duration: float = 11.0,
    target_words: int = 24,
    min_words: int = 7,
    max_words: int = 34,
    pause: float = 0.5,
) -> TranscriptSegmenter:
    return TranscriptSegmenter(
        SegmentSizing(
            target_duration_seconds=target_duration,
            min_duration_seconds=min_duration,
            max_duration_seconds=max_duration,
            target_word_count=target_words,
            min_word_count=min_words,
            max_word_count=max_words,
            pause_seconds=pause,
        )
    )


def _words(
    count: int,
    *,
    speaker: str | None = "SPEAKER_00",
    step: float = 0.3,
    duration: float = 0.2,
) -> list[dict[str, Any]]:
    return [
        {
            "word": f"w{index}",
            "start": index * step,
            "end": index * step + duration,
            "speaker": speaker,
            "speaker_confidence": 0.9,
        }
        for index in range(count)
    ]


def _raw_segment(words: list[dict[str, Any]]) -> dict[str, Any]:
    starts = [word["start"] for word in words if word.get("start") is not None]
    ends = [word["end"] for word in words if word.get("end") is not None]
    return {
        "start": min(starts) if starts else 0.0,
        "end": max(ends) if ends else 20.0,
        "text": "source text",
        "words": words,
        "language": "en",
    }


def _word_counts(segments: list[dict[str, Any]]) -> list[int]:
    return [int(segment["word_count"]) for segment in segments]


class TestAlignedWordSegmentation:
    def test_short_same_speaker_segment_remains_one_segment(self) -> None:
        words = _words(8)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert len(segments) == 1
        assert segments[0]["word_count"] == 8
        assert segments[0]["speaker"] == "SPEAKER_00"

    def test_long_single_speaker_speech_is_split_and_timestamps_are_exact(self) -> None:
        words = _words(40)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert len(segments) == 2
        assert _word_counts(segments) == [20, 20]
        assert segments[0]["start"] == words[0]["start"]
        assert segments[0]["end"] == words[19]["end"]
        assert segments[1]["start"] == words[20]["start"]
        assert segments[1]["end"] == words[-1]["end"]

    def test_speaker_change_is_a_hard_boundary(self) -> None:
        words = _words(4, speaker="SPEAKER_00") + _words(
            4,
            speaker="SPEAKER_01",
        )
        for index, word in enumerate(words):
            word["start"] = index * 0.3
            word["end"] = index * 0.3 + 0.2

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert [segment["speaker"] for segment in segments] == [
            "SPEAKER_00",
            "SPEAKER_01",
        ]
        assert _word_counts(segments) == [4, 4]

    @pytest.mark.parametrize(
        ("boundary_kind", "expected_first_count"),
        [
            ("terminal", 5),
            ("pause", 5),
            ("weak", 5),
            ("ordinary", 6),
        ],
    )
    def test_boundary_preference(
        self,
        boundary_kind: str,
        expected_first_count: int,
    ) -> None:
        words = _words(12, step=0.2, duration=0.15)
        if boundary_kind == "terminal":
            words[4]["word"] = "sentence."
        elif boundary_kind == "pause":
            for index in range(5, len(words)):
                words[index]["start"] += 0.6
                words[index]["end"] += 0.6
        elif boundary_kind == "weak":
            words[4]["word"] = "clause,"

        segmenter = _segmenter(
            target_duration=6.0,
            min_duration=0.1,
            max_duration=100.0,
            target_words=6,
            min_words=3,
            max_words=10,
        )
        segments = segmenter.post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [
            expected_first_count,
            12 - expected_first_count,
        ]

    def test_pause_inside_under_max_group_creates_boundary(self) -> None:
        words = _words(16, step=0.3, duration=0.2)
        pause = 0.6
        for index in range(8, len(words)):
            words[index]["start"] += pause
            words[index]["end"] += pause

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [8, 8]
        assert segments[0]["start"] == words[0]["start"]
        assert segments[0]["end"] == words[7]["end"]
        assert segments[1]["start"] == words[8]["start"]
        assert segments[1]["end"] == words[-1]["end"]

    def test_tiny_one_word_tail_after_pause_stays_attached(self) -> None:
        words = _words(9, step=0.3, duration=0.2)
        pause = 0.6
        words[-1]["start"] += pause
        words[-1]["end"] += pause

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [9]
        assert segments[0]["start"] == words[0]["start"]
        assert segments[0]["end"] == words[-1]["end"]

    def test_tiny_one_word_prefix_before_pause_stays_attached(self) -> None:
        words = _words(9, step=0.3, duration=0.2)
        pause = 0.6
        for index in range(1, len(words)):
            words[index]["start"] += pause
            words[index]["end"] += pause

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [9]

    def test_standalone_one_word_utterance_can_split_on_pause(self) -> None:
        words = _words(8, step=0.3, duration=0.2)
        words[0]["end"] = words[0]["start"] + 0.6
        shift = (words[0]["end"] + 0.6) - words[1]["start"]
        for index in range(1, len(words)):
            words[index]["start"] += shift
            words[index]["end"] += shift

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [1, 7]
        assert segments[0]["end"] == words[0]["end"]
        assert segments[1]["start"] == words[1]["start"]

    def test_pause_then_long_continuous_speech_uses_both_splitters(self) -> None:
        words = _words(48, step=0.3, duration=0.2)
        pause = 0.6
        for index in range(8, len(words)):
            words[index]["start"] += pause
            words[index]["end"] += pause

        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [8, 20, 20]
        assert segments[0]["end"] == words[7]["end"]
        assert segments[1]["start"] == words[8]["start"]
        assert segments[1]["end"] == words[27]["end"]
        assert segments[2]["start"] == words[28]["start"]

    def test_missing_timestamps_do_not_invent_pauses(self) -> None:
        words = _words(10)
        words[4]["end"] = None
        words[5]["start"] = None
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [10]

    def test_final_merge_does_not_join_pause_split_segments(self) -> None:
        words = _words(16, step=0.3, duration=0.2)
        pause = 0.6
        for index in range(8, len(words)):
            words[index]["start"] += pause
            words[index]["end"] += pause

        raw_segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(raw_segments) == [8, 8]
        merged = merge_transcript_segments(
            [
                ModelTranscriptSegment(
                    start_seconds=segment["start"],
                    end_seconds=segment["end"],
                    text=segment["text"],
                    speaker=segment.get("speaker"),
                    word_count=segment["word_count"],
                )
                for segment in raw_segments
            ]
        )
        assert len(merged) == 2
        assert [segment.word_count for segment in merged] == [8, 8]

    def test_acceptable_group_above_target_is_not_greedily_split(self) -> None:
        words = _words(34, step=0.25, duration=0.15)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [34]

    @pytest.mark.parametrize(
        ("count", "expected"),
        [
            (45, [22, 23]),
            (60, [30, 30]),
            (65, [32, 33]),
        ],
    )
    def test_long_groups_are_globally_rebalanced(
        self,
        count: int,
        expected: list[int],
    ) -> None:
        words = _words(count, step=0.15, duration=0.1)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == expected

    def test_hard_duration_and_word_limits_are_never_exceeded(self) -> None:
        words = _words(90, step=0.3, duration=0.2)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert len(segments) > 1
        for segment in segments:
            assert segment["end"] - segment["start"] <= 11.0
            assert segment["word_count"] <= 34

    def test_duration_driven_split_is_balanced_without_a_short_tail(self) -> None:
        words = _words(18, step=1.0, duration=0.8)
        segmenter = _segmenter(
            target_duration=7.0,
            min_duration=2.0,
            max_duration=11.0,
            target_words=20,
            min_words=1,
            max_words=100,
        )
        segments = segmenter.post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [9, 9]
        assert all(
            2.0 <= segment["end"] - segment["start"] <= 11.0
            for segment in segments
        )

    def test_non_diarized_words_are_still_bounded(self) -> None:
        words = _words(40, speaker=None)
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert _word_counts(segments) == [20, 20]
        assert all(segment["speaker"] is None for segment in segments)

    def test_chinese_without_whitespace_uses_aligned_entries(self) -> None:
        characters = list("这是一个没有空格的中文分段测试")
        words = _words(len(characters), step=0.2, duration=0.15)
        for word, character in zip(words, characters, strict=True):
            word["word"] = character

        segmenter = _segmenter(
            target_duration=6.0,
            min_duration=0.1,
            max_duration=100.0,
            target_words=6,
            min_words=3,
            max_words=8,
        )
        segments = segmenter.post_process_segments([_raw_segment(words)])
        assert len(segments) == 2
        assert sum(_word_counts(segments)) == len(characters)
        assert " " not in "".join(segment["text"] for segment in segments)

    def test_missing_endpoint_timestamps_use_existing_safe_fallbacks(self) -> None:
        words = _words(5)
        for word in words:
            word["start"] = None
        raw = _raw_segment(words)
        raw["start"] = 1.25
        segments = _segmenter().post_process_segments([raw])
        assert segments[0]["start"] == 1.25
        assert segments[0]["end"] == words[-1]["end"]

        words = _words(5)
        for word in words:
            word["end"] = None
        raw = _raw_segment(words)
        raw["end"] = 4.75
        segments = _segmenter().post_process_segments([raw])
        assert segments[0]["start"] == words[0]["start"]
        assert segments[0]["end"] == 4.75

        words = _words(5)
        words[0]["start"] = None
        words[-1]["end"] = None
        segments = _segmenter().post_process_segments([_raw_segment(words)])
        assert segments[0]["start"] == words[1]["start"]
        assert segments[0]["end"] == words[-2]["end"]


class TestSegmentationConfiguration:
    def test_invalid_limit_order_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="minimum <= target <= maximum"):
            Settings(
                _env_file=None,
                whisperx_segment_min_duration_seconds=8.0,
                whisperx_segment_target_duration_seconds=7.0,
            )

    def test_from_settings_forwards_segment_limits(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, Any] = {}

        def fake_init(self: WhisperXRuntime, **kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(WhisperXRuntime, "__init__", fake_init)
        monkeypatch.setattr(
            "telegram_agent.core.whisperx.runtime.settings",
            Settings(
                _env_file=None,
                whisperx_segment_target_duration_seconds=6.5,
                whisperx_segment_min_duration_seconds=1.5,
                whisperx_segment_max_duration_seconds=10.5,
                whisperx_segment_target_word_count=22,
                whisperx_segment_min_word_count=6,
                whisperx_segment_max_word_count=32,
                whisperx_segment_pause_seconds=0.45,
            ),
        )
        WhisperXRuntime.from_settings()
        assert captured["segment_target_duration_seconds"] == 6.5
        assert captured["segment_min_duration_seconds"] == 1.5
        assert captured["segment_max_duration_seconds"] == 10.5
        assert captured["segment_target_word_count"] == 22
        assert captured["segment_min_word_count"] == 6
        assert captured["segment_max_word_count"] == 32
        assert captured["segment_pause_seconds"] == 0.45
