"""Unit tests for Whisper segment merge heuristics."""

from __future__ import annotations

from telegram_agent.core.whisperx.common.results import ModelTranscriptSegment
from telegram_agent.core.whisperx.segmentation import (
    ends_with_terminal_punctuation,
    join_segment_texts,
    merge_transcript_segments,
    should_merge_segments,
)


def _seg(
    start: float,
    end: float,
    text: str,
    *,
    speaker: str | None = None,
    word_count: int | None = None,
) -> ModelTranscriptSegment:
    return ModelTranscriptSegment(
        start_seconds=start,
        end_seconds=end,
        text=text,
        speaker=speaker,
        word_count=word_count,
    )


class TestEndsWithTerminalPunctuation:
    def test_period(self) -> None:
        assert ends_with_terminal_punctuation("Hello.") is True

    def test_exclamation(self) -> None:
        assert ends_with_terminal_punctuation("Wow!") is True

    def test_question(self) -> None:
        assert ends_with_terminal_punctuation("What?") is True

    def test_unicode_ellipsis(self) -> None:
        assert ends_with_terminal_punctuation("Wait…") is True

    def test_ascii_ellipsis(self) -> None:
        assert ends_with_terminal_punctuation("Wait...") is True

    def test_trailing_whitespace(self) -> None:
        assert ends_with_terminal_punctuation("Done.  ") is True

    def test_incomplete(self) -> None:
        assert ends_with_terminal_punctuation("Where did") is False

    def test_comma(self) -> None:
        assert ends_with_terminal_punctuation("Hello,") is False

    def test_empty(self) -> None:
        assert ends_with_terminal_punctuation("") is False
        assert ends_with_terminal_punctuation("   ") is False


class TestJoinSegmentTexts:
    def test_word_join_with_space(self) -> None:
        assert join_segment_texts("Hello,", "world") == "Hello, world"

    def test_punctuation_no_space(self) -> None:
        assert join_segment_texts("end", ".") == "end."

    def test_empty_sides(self) -> None:
        assert join_segment_texts("", "hi") == "hi"
        assert join_segment_texts("hi", "") == "hi"


class TestShouldMergeSegments:
    def test_small_gap_mid_sentence(self) -> None:
        current = _seg(20.759, 20.959, "Where did")
        nxt = _seg(20.999, 21.619, "you get him?")
        assert should_merge_segments(current, nxt) is True

    def test_small_gap_after_period_always_merges(self) -> None:
        current = _seg(1.0, 2.0, "That would be Marcel.")
        nxt = _seg(2.1, 3.0, "Do you want to say hi?")
        assert should_merge_segments(current, nxt) is True

    def test_large_gap_never_merges(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.7, 3.0, "you get him?")
        assert should_merge_segments(current, nxt) is False

    def test_borderline_gap_incomplete_merges(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.4, 3.0, "you get him?")
        assert should_merge_segments(current, nxt) is True

    def test_borderline_gap_terminal_keeps_separate(self) -> None:
        for text in ("Done.", "Wow!", "What?", "Wait…", "Wait..."):
            current = _seg(1.0, 2.0, text)
            nxt = _seg(2.4, 3.0, "Next sentence.")
            assert should_merge_segments(current, nxt) is False, text

    def test_gap_exactly_at_thresholds(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.25, 3.0, "you get him?")
        assert should_merge_segments(current, nxt) is True

        current_term = _seg(1.0, 2.0, "Done.")
        assert should_merge_segments(current_term, nxt) is False

        nxt_far = _seg(2.55, 3.0, "more")
        assert should_merge_segments(current, nxt_far) is False
        assert should_merge_segments(current_term, nxt_far) is False

    def test_different_speakers_blocked_when_same_speaker_only(self) -> None:
        current = _seg(0.0, 1.0, "Where did", speaker="SPEAKER_05")
        nxt = _seg(1.04, 2.0, "you get him?", speaker="SPEAKER_06")
        assert should_merge_segments(current, nxt, same_speaker_only=True) is False
        assert should_merge_segments(current, nxt, same_speaker_only=False) is True

    def test_pause_gap_never_merges_mid_sentence(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.5, 3.5, "you get him?")
        assert should_merge_segments(current, nxt) is False

    def test_gap_just_below_pause_uses_punctuation(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.49, 3.5, "you get him?")
        assert should_merge_segments(current, nxt) is True

        current_term = _seg(1.0, 2.0, "Done.")
        assert should_merge_segments(current_term, nxt) is False

    def test_custom_pause_seconds_blocks_smaller_gap(self) -> None:
        current = _seg(1.0, 2.0, "Where did")
        nxt = _seg(2.5, 3.5, "you get him?")
        assert should_merge_segments(current, nxt, pause_seconds=0.5) is False
        assert should_merge_segments(current, nxt, pause_seconds=0.55) is True

    def test_hard_duration_limit_overrides_always_merge_gap(self) -> None:
        current = _seg(0.0, 6.0, "first", word_count=10)
        nxt = _seg(6.01, 11.5, "second", word_count=10)
        assert (
            should_merge_segments(
                current,
                nxt,
                max_duration_seconds=11.0,
                max_word_count=34,
            )
            is False
        )

    def test_hard_word_limit_overrides_always_merge_gap(self) -> None:
        current = _seg(0.0, 3.0, "first", word_count=20)
        nxt = _seg(3.01, 6.0, "second", word_count=15)
        assert (
            should_merge_segments(
                current,
                nxt,
                max_duration_seconds=11.0,
                max_word_count=34,
            )
            is False
        )


class TestMergeTranscriptSegments:
    def test_empty_and_single(self) -> None:
        assert merge_transcript_segments([]) == []
        single = [_seg(0.0, 1.0, "Hi.")]
        assert merge_transcript_segments(single) == single

    def test_chain_of_three_tiny_gaps(self) -> None:
        segments = [
            _seg(0.0, 0.5, "Where"),
            _seg(0.55, 1.0, "did"),
            _seg(1.05, 1.5, "you get him?"),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 1
        assert merged[0].text == "Where did you get him?"
        assert merged[0].start_seconds == 0.0
        assert merged[0].end_seconds == 1.5

    def test_different_speakers_blocked_by_default(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Where did", speaker="SPEAKER_05"),
            _seg(1.04, 2.0, "you get him?", speaker="SPEAKER_06"),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 2

    def test_different_speakers_merge_when_option_disabled(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Where did", speaker="SPEAKER_05"),
            _seg(1.04, 2.0, "you get him?", speaker="SPEAKER_06"),
        ]
        merged = merge_transcript_segments(segments, same_speaker_only=False)
        assert len(merged) == 1
        assert merged[0].speaker == "SPEAKER_05"
        assert merged[0].text == "Where did you get him?"

    def test_same_speakers_still_merge(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Where did", speaker="SPEAKER_05"),
            _seg(1.04, 2.0, "you get him?", speaker="SPEAKER_05"),
        ]
        merged = merge_transcript_segments(segments, same_speaker_only=True)
        assert len(merged) == 1
        assert merged[0].text == "Where did you get him?"

    def test_unknown_speaker_does_not_block_merge(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Where did", speaker="SPEAKER_05"),
            _seg(1.04, 2.0, "you get him?", speaker=None),
        ]
        merged = merge_transcript_segments(segments, same_speaker_only=True)
        assert len(merged) == 1

    def test_large_gap_keeps_separate(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Hello."),
            _seg(2.0, 3.0, "World."),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 2
        assert merged[0].text == "Hello."
        assert merged[1].text == "World."

    def test_borderline_complete_sentence_keeps_separate(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Hello."),
            _seg(1.4, 2.0, "World."),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 2

    def test_mixed_merge_and_keep(self) -> None:
        segments = [
            _seg(0.0, 1.0, "Where did"),
            _seg(1.04, 2.0, "you get him?"),
            _seg(3.0, 4.0, "Much later."),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 2
        assert merged[0].text == "Where did you get him?"
        assert merged[1].text == "Much later."

    def test_does_not_recombine_pause_split_segments(self) -> None:
        segments = [
            _seg(0.0, 2.3, "first phrase here", speaker="SPEAKER_00", word_count=8),
            _seg(2.9, 5.2, "second phrase here", speaker="SPEAKER_00", word_count=8),
        ]
        merged = merge_transcript_segments(segments)
        assert len(merged) == 2
        assert [segment.text for segment in merged] == [
            "first phrase here",
            "second phrase here",
        ]

    def test_repeated_merge_does_not_recombine_oversized_segment(self) -> None:
        segments = [
            _seg(0.0, 3.5, "one", word_count=10),
            _seg(3.51, 7.0, "two", word_count=10),
            _seg(7.01, 10.5, "three", word_count=10),
        ]
        merged = merge_transcript_segments(
            segments,
            max_duration_seconds=8.0,
            max_word_count=25,
        )
        assert [segment.text for segment in merged] == ["one two", "three"]
        assert merged[0].word_count == 20

    def test_unicode_word_fallback_caps_no_whitespace_merge(self) -> None:
        segments = [
            _seg(0.0, 1.0, "你好世界"),
            _seg(1.01, 2.0, "再次见面"),
        ]
        merged = merge_transcript_segments(
            segments,
            max_duration_seconds=11.0,
            max_word_count=7,
        )
        assert len(merged) == 2
