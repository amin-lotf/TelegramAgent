from __future__ import annotations

from telegram_agent.core.chunking.common.commands import (
    ChunkingOptions,
    TranscriptSegmentInput,
)
from telegram_agent.core.chunking.services.strategies.transcript_segment_window import (
    TranscriptSegmentWindowChunker,
    estimate_tokens,
)


def _options(**overrides: int) -> ChunkingOptions:
    base = {
        "target_chunk_duration_ms": 60_000,
        "max_chunk_chars": 2_000,
        "max_chunk_tokens": 512,
        "overlap_duration_ms": 8_000,
        "overlap_segments": 1,
    }
    base.update(overrides)
    return ChunkingOptions(**base)


def _seg(
    index: int,
    start_ms: int,
    end_ms: int,
    text: str,
    speaker: str | None = None,
) -> TranscriptSegmentInput:
    return TranscriptSegmentInput(
        segment_index=index,
        start_ms=start_ms,
        end_ms=end_ms,
        text=text,
        speaker=speaker,
    )


def test_empty_and_whitespace_segments_yield_no_chunks() -> None:
    chunker = TranscriptSegmentWindowChunker()
    chunks = chunker.chunk(
        (
            _seg(0, 0, 1000, "   "),
            _seg(1, 1000, 2000, ""),
        ),
        options=_options(),
    )
    assert chunks == ()


def test_single_segment_chunk() -> None:
    chunker = TranscriptSegmentWindowChunker()
    chunks = chunker.chunk(
        (_seg(0, 0, 1500, "hello world", speaker="SPEAKER_00"),),
        options=_options(),
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.chunk_index == 0
    assert chunk.text == "hello world"
    assert chunk.start_ms == 0
    assert chunk.end_ms == 1500
    assert chunk.speakers == ("SPEAKER_00",)
    assert chunk.segment_index_start == 0
    assert chunk.segment_index_end == 0
    assert chunk.token_count == estimate_tokens("hello world")


def test_duration_limit_splits_windows() -> None:
    chunker = TranscriptSegmentWindowChunker()
    segments = tuple(
        _seg(i, i * 10_000, (i + 1) * 10_000, f"segment-{i}")
        for i in range(8)
    )
    chunks = chunker.chunk(
        segments,
        options=_options(
            target_chunk_duration_ms=25_000,
            max_chunk_chars=100_000,
            max_chunk_tokens=100_000,
            overlap_duration_ms=0,
            overlap_segments=0,
        ),
    )
    assert len(chunks) >= 3
    assert chunks[0].segment_index_start == 0
    assert all(chunk.end_ms >= chunk.start_ms for chunk in chunks)


def test_overlap_segments_preserves_progress() -> None:
    chunker = TranscriptSegmentWindowChunker()
    segments = tuple(
        _seg(i, i * 5_000, (i + 1) * 5_000, f"word-{i} " * 5)
        for i in range(6)
    )
    chunks = chunker.chunk(
        segments,
        options=_options(
            target_chunk_duration_ms=12_000,
            max_chunk_chars=100_000,
            max_chunk_tokens=100_000,
            overlap_duration_ms=0,
            overlap_segments=1,
        ),
    )
    assert len(chunks) >= 2
    # Overlap means second chunk should start at or before first chunk's last segment.
    assert chunks[1].segment_index_start <= chunks[0].segment_index_end
    # But still make forward progress on the core content.
    assert chunks[1].segment_index_end > chunks[0].segment_index_end or chunks[1].segment_index_start > chunks[0].segment_index_start


def test_speakers_collected_in_order() -> None:
    chunker = TranscriptSegmentWindowChunker()
    chunks = chunker.chunk(
        (
            _seg(0, 0, 1000, "a", speaker="SPEAKER_00"),
            _seg(1, 1000, 2000, "b", speaker="SPEAKER_01"),
            _seg(2, 2000, 3000, "c", speaker="SPEAKER_00"),
        ),
        options=_options(
            target_chunk_duration_ms=10_000,
            max_chunk_chars=100_000,
            max_chunk_tokens=100_000,
            overlap_duration_ms=0,
            overlap_segments=0,
        ),
    )
    assert len(chunks) == 1
    assert chunks[0].speakers == ("SPEAKER_00", "SPEAKER_01")


def test_oversized_single_segment_not_split() -> None:
    chunker = TranscriptSegmentWindowChunker()
    long_text = "x" * 5_000
    chunks = chunker.chunk(
        (_seg(0, 0, 90_000, long_text),),
        options=_options(
            target_chunk_duration_ms=10_000,
            max_chunk_chars=100,
            max_chunk_tokens=10,
            overlap_duration_ms=0,
            overlap_segments=0,
        ),
    )
    assert len(chunks) == 1
    assert chunks[0].text == long_text
