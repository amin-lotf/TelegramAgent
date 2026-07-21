from __future__ import annotations

from telegram_agent.core.chunking.common.commands import ChunkTranscriptCommand
from telegram_agent.core.chunking.common.results import TranscriptChunkingResult
from telegram_agent.core.chunking.common.types import ContentType
from telegram_agent.core.chunking.services.strategies.transcript_segment_window import (
    TranscriptSegmentWindowChunker,
)


class TranscriptChunkingService:
    def __init__(
        self,
        chunker: TranscriptSegmentWindowChunker | None = None,
    ) -> None:
        self._chunker = chunker or TranscriptSegmentWindowChunker()

    def chunk_transcript(self, command: ChunkTranscriptCommand) -> TranscriptChunkingResult:
        chunks = self._chunker.chunk(command.segments, options=command.options)
        return TranscriptChunkingResult(
            content_type=ContentType.TRANSCRIPT.value,
            strategy=self._chunker.strategy_name,
            chunk_count=len(chunks),
            chunks=chunks,
        )
