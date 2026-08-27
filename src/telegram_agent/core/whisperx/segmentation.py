from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from telegram_agent.core.whisperx.common.const import (
    DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
    DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
)
from telegram_agent.core.whisperx.common.results import ModelTranscriptSegment

MERGE_GAP_ALWAYS = 0.25
MERGE_GAP_NEVER = 0.55
TERMINAL_PUNCTUATION = (".", "!", "?", "…", "。", "！", "？")
WEAK_PUNCTUATION = (",", ";", ":", "，", "；", "：", "、")


def _is_no_space_character(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
        or 0x3040 <= codepoint <= 0x30FF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _fallback_word_unit_count(text: str) -> int:
    """Estimate word units only when exact aligned-word metadata is unavailable."""
    count = 0
    in_spaced_word = False
    for character in text:
        if character.isspace():
            in_spaced_word = False
        elif _is_no_space_character(character):
            count += 1
            in_spaced_word = False
        elif character.isalnum() or character in "'’":
            if not in_spaced_word:
                count += 1
                in_spaced_word = True
        else:
            in_spaced_word = False
    return count


def ends_with_terminal_punctuation(text: str) -> bool:
    """True if text ends with sentence-final punctuation (. ! ? … or ...)."""
    stripped = text.rstrip()
    if not stripped:
        return False
    if stripped.endswith("..."):
        return True
    return stripped[-1] in TERMINAL_PUNCTUATION


def join_segment_texts(left: str, right: str) -> str:
    """Join two segment texts with a single space when needed."""
    left = left.strip()
    right = right.strip()
    if not left:
        return right
    if not right:
        return left
    if right[0] in ".,!?;:%)]}'\"…。！？；：，、":
        return f"{left}{right}"
    if _is_no_space_character(left[-1]) and _is_no_space_character(right[0]):
        return f"{left}{right}"
    return f"{left} {right}"


def _model_segment_word_count(segment: ModelTranscriptSegment) -> int:
    if segment.word_count is not None:
        return segment.word_count
    return _fallback_word_unit_count(segment.text)


def should_merge_segments(
    current: ModelTranscriptSegment,
    next_segment: ModelTranscriptSegment,
    *,
    same_speaker_only: bool = True,
    max_duration_seconds: float = DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
    max_word_count: int = DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
    pause_seconds: float = DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
) -> bool:
    """Decide whether two adjacent segments should be merged.

    Rules:
    - if same_speaker_only and both speakers are set and differ → never merge
    - if the combined segment exceeds a configured hard size → never merge
    - gap >= pause_seconds → never merge
    - gap < 0.25  → always merge
    - gap > 0.55  → never merge
    - otherwise   → merge only if current text does not end with terminal punctuation

    When same_speaker_only is True, a missing speaker on either side does not block
    the merge (only known different speakers do).
    """
    if same_speaker_only:
        left_speaker = current.speaker
        right_speaker = next_segment.speaker
        if (
            left_speaker is not None
            and right_speaker is not None
            and left_speaker != right_speaker
        ):
            return False

    merged_duration = next_segment.end_seconds - current.start_seconds
    if merged_duration > max_duration_seconds:
        return False

    merged_word_count = (
        _model_segment_word_count(current)
        + _model_segment_word_count(next_segment)
    )
    if merged_word_count > max_word_count:
        return False

    gap = next_segment.start_seconds - current.end_seconds
    if gap >= pause_seconds:
        return False
    if gap < MERGE_GAP_ALWAYS:
        return True
    if gap > MERGE_GAP_NEVER:
        return False
    return not ends_with_terminal_punctuation(current.text)


def _merge_pair(
    left: ModelTranscriptSegment,
    right: ModelTranscriptSegment,
) -> ModelTranscriptSegment:
    return ModelTranscriptSegment(
        start_seconds=left.start_seconds,
        end_seconds=right.end_seconds,
        text=join_segment_texts(left.text, right.text),
        language=left.language if left.language is not None else right.language,
        language_probability=(
            left.language_probability
            if left.language_probability is not None
            else right.language_probability
        ),
        speaker=left.speaker,
        speaker_confidence=left.speaker_confidence,
        word_count=(
            _model_segment_word_count(left)
            + _model_segment_word_count(right)
        ),
    )


def merge_transcript_segments(
    segments: list[ModelTranscriptSegment],
    *,
    same_speaker_only: bool = True,
    max_duration_seconds: float = DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
    max_word_count: int = DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
    pause_seconds: float = DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
) -> list[ModelTranscriptSegment]:
    """Merge adjacent Whisper segments by gap and terminal punctuation."""
    if len(segments) <= 1:
        return list(segments)

    merged: list[ModelTranscriptSegment] = [segments[0]]
    for next_segment in segments[1:]:
        current = merged[-1]
        if should_merge_segments(
            current,
            next_segment,
            same_speaker_only=same_speaker_only,
            max_duration_seconds=max_duration_seconds,
            max_word_count=max_word_count,
            pause_seconds=pause_seconds,
        ):
            merged[-1] = _merge_pair(current, next_segment)
        else:
            merged.append(next_segment)
    return merged


@dataclass(frozen=True)
class SegmentWord:
    text: str
    speaker: str | None
    start_seconds: float | None
    end_seconds: float | None
    speaker_confidence: float | None


@dataclass(frozen=True)
class SegmentSizing:
    target_duration_seconds: float
    min_duration_seconds: float
    max_duration_seconds: float
    target_word_count: int
    min_word_count: int
    max_word_count: int
    pause_seconds: float

    def __post_init__(self) -> None:
        if not (
            0 < self.min_duration_seconds
            <= self.target_duration_seconds
            <= self.max_duration_seconds
        ):
            raise ValueError(
                "WhisperX segment duration limits must satisfy "
                "0 < minimum <= target <= maximum"
            )
        if not (
            0 < self.min_word_count
            <= self.target_word_count
            <= self.max_word_count
        ):
            raise ValueError(
                "WhisperX segment word-count limits must satisfy "
                "0 < minimum <= target <= maximum"
            )
        if self.pause_seconds <= 0:
            raise ValueError("whisperx_segment_pause_seconds must be greater than zero")


class TranscriptSegmenter:
    """Split aligned Whisper words on speakers, pauses, and hard size limits."""

    def __init__(self, sizing: SegmentSizing) -> None:
        self._sizing = sizing

    def post_process_segments(
        self,
        raw_segments: list[Any],
    ) -> list[dict[str, Any]]:
        normalized_segments: list[dict[str, Any]] = []

        for raw_segment in raw_segments:
            if not isinstance(raw_segment, dict):
                continue

            split_segments = self._split_segment_by_speaker(raw_segment)

            if split_segments is None:
                normalized_segments.append(raw_segment)
                continue

            normalized_segments.extend(split_segments)

        return normalized_segments

    def _split_segment_by_speaker(
        self,
        raw_segment: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        raw_words = raw_segment.get("words")

        if not isinstance(raw_words, list) or not raw_words:
            return None

        words = self._extract_segment_words(raw_words)

        if not words:
            return None

        grouped_words: list[list[SegmentWord]] = []
        grouped_speakers: list[str | None] = []
        current_words: list[SegmentWord] = []
        current_speaker: str | None = None

        for word in words:
            if (
                current_words
                and word.speaker is not None
                and current_speaker is not None
                and word.speaker != current_speaker
            ):
                grouped_words.append(current_words)
                grouped_speakers.append(current_speaker)
                current_words = []
                current_speaker = word.speaker

            if current_speaker is None and word.speaker is not None:
                current_speaker = word.speaker

            current_words.append(word)

        if current_words:
            grouped_words.append(current_words)
            grouped_speakers.append(current_speaker)

        if not grouped_words:
            return None

        bounded_groups: list[tuple[list[SegmentWord], str | None]] = []
        for group_words, speaker in zip(grouped_words, grouped_speakers, strict=True):
            bounded_groups.extend(
                (chunk_words, speaker)
                for chunk_words in self._split_same_speaker_word_group(group_words)
            )

        normalized_segments: list[dict[str, Any]] = []

        for index, (group_words, speaker) in enumerate(bounded_groups):
            segment = self._build_speaker_homogeneous_segment(
                raw_segment=raw_segment,
                group_words=group_words,
                speaker=speaker,
                previous_segment=normalized_segments[-1] if normalized_segments else None,
                next_group_words=(
                    bounded_groups[index + 1][0]
                    if index + 1 < len(bounded_groups)
                    else None
                ),
            )

            if segment is None:
                return None

            normalized_segments.append(segment)

        return normalized_segments

    def _split_same_speaker_word_group(
        self,
        words: list[SegmentWord],
    ) -> list[list[SegmentWord]]:
        """Split one speaker run on pauses, then partition to hard limits."""
        if not words:
            return [words]

        chunks: list[list[SegmentWord]] = []
        for pause_run in self._split_word_group_on_pauses(words):
            chunks.extend(self._partition_word_group_to_limits(pause_run))
        return chunks

    def _split_word_group_on_pauses(
        self,
        words: list[SegmentWord],
    ) -> list[list[SegmentWord]]:
        """Hard-split a speaker run at meaningful pauses, skipping tiny tails."""
        if len(words) <= 1:
            return [words]

        runs: list[list[SegmentWord]] = []
        start = 0
        for index in range(1, len(words)):
            if not self._is_meaningful_pause(words[index - 1], words[index]):
                continue
            left = words[start:index]
            right = words[index:]
            if self._chunk_is_tiny_tail(left) or self._chunk_is_tiny_tail(right):
                continue
            runs.append(left)
            start = index
        runs.append(words[start:])
        return runs

    def _is_meaningful_pause(
        self,
        left: SegmentWord,
        right: SegmentWord,
    ) -> bool:
        left_end = left.end_seconds
        right_start = right.start_seconds
        return (
            left_end is not None
            and right_start is not None
            and right_start - left_end >= self._sizing.pause_seconds
        )

    def _chunk_is_tiny_tail(
        self,
        words: list[SegmentWord],
    ) -> bool:
        if len(words) >= 2:
            return False
        duration = self._word_chunk_duration(words)
        return duration is None or duration < self._sizing.pause_seconds

    def _partition_word_group_to_limits(
        self,
        words: list[SegmentWord],
    ) -> list[list[SegmentWord]]:
        """Globally partition one continuous run without creating greedy tails."""
        if not words or self._chunk_within_hard_limits(words):
            return [words]

        word_count = len(words)

        @lru_cache(maxsize=None)
        def minimum_chunks_from(start: int) -> int:
            if start == word_count:
                return 0

            best = word_count + 1
            max_end = min(
                word_count,
                start + self._sizing.max_word_count,
            )
            for end in range(start + 1, max_end + 1):
                if not self._chunk_within_hard_limits(words[start:end]):
                    continue
                remaining = minimum_chunks_from(end)
                if remaining <= word_count:
                    best = min(best, 1 + remaining)
            return best

        chunk_count = minimum_chunks_from(0)
        if chunk_count > word_count:
            # An indivisible aligned entry can itself exceed the duration maximum.
            return [words]

        total_duration = self._word_chunk_duration(words)
        ideal_duration = (
            total_duration / chunk_count if total_duration is not None else None
        )
        ideal_word_count = word_count / chunk_count

        Score = tuple[int, float, int, float, float]
        Partition = tuple[Score, tuple[int, ...]]

        @lru_cache(maxsize=None)
        def best_partition(start: int, chunks_left: int) -> Partition | None:
            if chunks_left == 0:
                if start == word_count:
                    return ((0, 0.0, 0, 0.0, 0.0), ())
                return None

            max_end = min(
                word_count,
                start + self._sizing.max_word_count,
            )
            best: Partition | None = None
            for end in range(start + 1, max_end + 1):
                words_left = word_count - end
                if words_left < chunks_left - 1:
                    break

                chunk_words = words[start:end]
                if not self._chunk_within_hard_limits(chunk_words):
                    continue

                remainder = best_partition(end, chunks_left - 1)
                if remainder is None:
                    continue

                chunk_score = self._word_chunk_partition_score(
                    words=chunk_words,
                    ideal_duration=ideal_duration,
                    ideal_word_count=ideal_word_count,
                    boundary_penalty=(
                        self._word_boundary_penalty(words, end)
                        if end < word_count
                        else 0.0
                    ),
                )
                remainder_score, remainder_ends = remainder
                score: Score = (
                    chunk_score[0] + remainder_score[0],
                    chunk_score[1] + remainder_score[1],
                    chunk_score[2] + remainder_score[2],
                    chunk_score[3] + remainder_score[3],
                    chunk_score[4] + remainder_score[4],
                )
                candidate = (score, (end, *remainder_ends))
                if best is None or candidate < best:
                    best = candidate
            return best

        partition = best_partition(0, chunk_count)
        if partition is None:
            return [words]

        chunks: list[list[SegmentWord]] = []
        start = 0
        for end in partition[1]:
            chunks.append(words[start:end])
            start = end
        return chunks

    def _word_chunk_duration(
        self,
        words: list[SegmentWord],
    ) -> float | None:
        start = self._first_word_start(words)
        end = self._last_word_end(words)
        if start is None or end is None or end < start:
            return None
        return end - start

    def _chunk_within_hard_limits(
        self,
        words: list[SegmentWord],
    ) -> bool:
        if len(words) > self._sizing.max_word_count:
            return False
        duration = self._word_chunk_duration(words)
        return (
            duration is None
            or duration <= self._sizing.max_duration_seconds
        )

    def _word_chunk_partition_score(
        self,
        *,
        words: list[SegmentWord],
        ideal_duration: float | None,
        ideal_word_count: float,
        boundary_penalty: float,
    ) -> tuple[int, float, int, float, float]:
        sizing = self._sizing
        duration = self._word_chunk_duration(words)
        duration_under_minimum = int(
            duration is not None and duration < sizing.min_duration_seconds
        )
        duration_shortfall = (
            max(0.0, sizing.min_duration_seconds - duration)
            / sizing.min_duration_seconds
            if duration is not None
            else 0.0
        )

        count = len(words)
        word_under_minimum = int(count < sizing.min_word_count)
        word_shortfall = (
            max(0, sizing.min_word_count - count) / sizing.min_word_count
        )

        duration_cost = 0.0
        if duration is not None:
            duration_cost = 4.0 * (
                (duration - sizing.target_duration_seconds)
                / sizing.target_duration_seconds
            ) ** 2
            if ideal_duration is not None:
                duration_cost += 8.0 * (
                    (duration - ideal_duration) / sizing.target_duration_seconds
                ) ** 2

        word_cost = (
            (count - sizing.target_word_count) / sizing.target_word_count
        ) ** 2
        word_cost += 2.0 * (
            (count - ideal_word_count) / sizing.target_word_count
        ) ** 2

        return (
            duration_under_minimum,
            duration_shortfall,
            word_under_minimum,
            word_shortfall,
            duration_cost + word_cost + boundary_penalty,
        )

    def _word_boundary_penalty(
        self,
        words: list[SegmentWord],
        boundary: int,
    ) -> float:
        left = words[boundary - 1]
        if ends_with_terminal_punctuation(left.text):
            return 0.0

        if self._is_meaningful_pause(left, words[boundary]):
            return 0.1

        if left.text.rstrip().endswith(WEAK_PUNCTUATION):
            return 0.4
        return 1.0

    def _build_speaker_homogeneous_segment(
        self,
        *,
        raw_segment: dict[str, Any],
        group_words: list[SegmentWord],
        speaker: str | None,
        previous_segment: dict[str, Any] | None,
        next_group_words: list[SegmentWord] | None,
    ) -> dict[str, Any] | None:
        text = self._join_word_texts([word.text for word in group_words])

        if not text:
            return None

        raw_start = self._get_float(raw_segment, "start")
        raw_end = self._get_float(raw_segment, "end")

        start = self._first_word_start(group_words)
        end = self._last_word_end(group_words)

        if start is None:
            if previous_segment is not None:
                start = self._get_float(previous_segment, "end")
            if start is None and raw_start is not None:
                start = raw_start

        if end is None:
            if next_group_words is not None:
                end = self._first_word_start(next_group_words)

            if end is None and raw_end is not None:
                end = raw_end

        if start is None or end is None or end < start:
            return None

        segment: dict[str, Any] = {
            "start": start,
            "end": end,
            "text": text,
            "language": raw_segment.get("language"),
            "language_probability": raw_segment.get("language_probability"),
            "speaker": speaker,
            "word_count": len(group_words),
        }

        speaker_confidence = self._average_speaker_confidence(group_words)

        if speaker_confidence is not None:
            segment["speaker_confidence"] = speaker_confidence

        return segment

    def _extract_segment_words(
        self,
        raw_words: list[Any],
    ) -> list[SegmentWord]:
        words: list[SegmentWord] = []

        for raw_word in raw_words:
            if not isinstance(raw_word, dict):
                continue

            text = self._extract_word_text(raw_word)

            if text is None:
                continue

            words.append(
                SegmentWord(
                    text=text,
                    speaker=self._normalize_text(raw_word.get("speaker")),
                    start_seconds=self._get_float(raw_word, "start"),
                    end_seconds=self._get_float(raw_word, "end"),
                    speaker_confidence=self._get_float(
                        raw_word,
                        "speaker_confidence",
                        "speaker_probability",
                    ),
                )
            )

        return words

    def _extract_word_text(
        self,
        raw_word: dict[str, Any],
    ) -> str | None:
        for key in ("word", "text"):
            value = raw_word.get(key)

            if value is None:
                continue

            text = str(value)

            if text.strip():
                return text

        return None

    def _join_word_texts(
        self,
        raw_words: list[str],
    ) -> str:
        parts: list[str] = []

        for raw_word in raw_words:
            if not raw_word.strip():
                continue

            if not parts:
                parts.append(raw_word.strip())
                continue

            stripped_word = raw_word.strip()

            if raw_word[:1].isspace():
                parts.append(raw_word)
                continue

            if stripped_word.startswith(
                (
                    "'", ".", ",", "!", "?", ":", ";", "%", ")", "]", "}",
                    "…", "。", "！", "？", "，", "；", "：", "、",
                )
            ):
                parts.append(stripped_word)
                continue

            if stripped_word.startswith("n't"):
                parts.append(stripped_word)
                continue

            previous_character = parts[-1].rstrip()[-1:]
            if (
                previous_character
                and _is_no_space_character(previous_character)
                and _is_no_space_character(stripped_word[0])
            ):
                parts.append(stripped_word)
                continue

            parts.append(f" {stripped_word}")

        return "".join(parts).strip()

    def _first_word_start(
        self,
        words: list[SegmentWord],
    ) -> float | None:
        for word in words:
            if word.start_seconds is not None:
                return word.start_seconds

        return None

    def _last_word_end(
        self,
        words: list[SegmentWord],
    ) -> float | None:
        for word in reversed(words):
            if word.end_seconds is not None:
                return word.end_seconds

        return None

    def _average_speaker_confidence(
        self,
        words: list[SegmentWord],
    ) -> float | None:
        values = [
            word.speaker_confidence
            for word in words
            if word.speaker_confidence is not None
        ]

        if not values:
            return None

        return sum(values) / len(values)

    def _get_float(
        self,
        data: dict[str, Any],
        *keys: str,
    ) -> float | None:
        for key in keys:
            value = data.get(key)

            if value is None:
                continue

            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        return None

    def _normalize_text(
        self,
        value: object,
    ) -> str | None:
        if value is None:
            return None

        text = str(value).strip()

        if not text:
            return None

        return text
