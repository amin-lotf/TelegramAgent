from __future__ import annotations

from typing import Protocol

from telegram_agent.core.chunking.common.commands import (
    ChunkingOptions,
    TranscriptSegmentInput,
)
from telegram_agent.core.chunking.common.results import ChunkResult


class TranscriptChunker(Protocol):
    strategy_name: str

    def chunk(
        self,
        segments: tuple[TranscriptSegmentInput, ...],
        *,
        options: ChunkingOptions,
    ) -> tuple[ChunkResult, ...]:
        ...
