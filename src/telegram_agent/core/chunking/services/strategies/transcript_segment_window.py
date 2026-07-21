from __future__ import annotations

from telegram_agent.core.chunking.common.commands import (
    ChunkingOptions,
    TranscriptSegmentInput,
)
from telegram_agent.core.chunking.common.const import TRANSCRIPT_SEGMENT_WINDOW_STRATEGY
from telegram_agent.core.chunking.common.results import ChunkResult


def estimate_tokens(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


class TranscriptSegmentWindowChunker:
    """Segment-aware, time-aware windowing that never splits mid-segment."""

    strategy_name = TRANSCRIPT_SEGMENT_WINDOW_STRATEGY

    def chunk(
        self,
        segments: tuple[TranscriptSegmentInput, ...],
        *,
        options: ChunkingOptions,
    ) -> tuple[ChunkResult, ...]:
        usable = tuple(
            segment
            for segment in segments
            if segment.text.strip() and segment.end_ms >= segment.start_ms
        )
        if not usable:
            return ()

        windows: list[list[TranscriptSegmentInput]] = []
        start = 0
        n = len(usable)

        while start < n:
            end = start
            char_total = 0
            token_total = 0
            window_start_ms = usable[start].start_ms

            while end < n:
                segment = usable[end]
                segment_text = segment.text.strip()
                segment_chars = len(segment_text)
                segment_tokens = estimate_tokens(segment_text)
                duration_ms = segment.end_ms - window_start_ms

                would_exceed = end > start and (
                    duration_ms > options.target_chunk_duration_ms
                    or char_total + segment_chars > options.max_chunk_chars
                    or token_total + segment_tokens > options.max_chunk_tokens
                )
                if would_exceed:
                    break

                char_total += segment_chars
                token_total += segment_tokens
                end += 1

            if end == start:
                # Single oversized segment: emit alone, never split mid-segment.
                end = start + 1

            windows.append(list(usable[start:end]))
            if end >= n:
                break

            step = self._step_size(
                window=usable[start:end],
                options=options,
            )
            start = start + step

        return tuple(
            self._to_chunk(index=index, window=window)
            for index, window in enumerate(windows)
        )

    def _step_size(
        self,
        *,
        window: tuple[TranscriptSegmentInput, ...] | list[TranscriptSegmentInput],
        options: ChunkingOptions,
    ) -> int:
        """How many segments to advance so the next window overlaps but still progresses."""
        window_len = len(window)
        if window_len <= 1:
            return 1

        overlap_count = 0
        if options.overlap_segments > 0:
            overlap_count = max(overlap_count, min(options.overlap_segments, window_len - 1))

        if options.overlap_duration_ms > 0:
            boundary_end_ms = window[-1].end_ms
            duration_overlap = 0
            for offset in range(1, window_len):
                segment = window[window_len - offset]
                if boundary_end_ms - segment.start_ms > options.overlap_duration_ms:
                    break
                duration_overlap = offset
            overlap_count = max(overlap_count, min(duration_overlap, window_len - 1))

        return max(1, window_len - overlap_count)

    @staticmethod
    def _to_chunk(
        *,
        index: int,
        window: list[TranscriptSegmentInput],
    ) -> ChunkResult:
        texts = [segment.text.strip() for segment in window if segment.text.strip()]
        text = " ".join(texts)
        speakers: list[str] = []
        for segment in window:
            if segment.speaker and segment.speaker not in speakers:
                speakers.append(segment.speaker)
        return ChunkResult(
            chunk_index=index,
            text=text,
            start_ms=window[0].start_ms,
            end_ms=window[-1].end_ms,
            char_count=len(text),
            token_count=estimate_tokens(text),
            segment_index_start=window[0].segment_index,
            segment_index_end=window[-1].segment_index,
            speakers=tuple(speakers),
        )
