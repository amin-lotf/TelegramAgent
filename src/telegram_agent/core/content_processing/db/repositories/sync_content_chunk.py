from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.commands import RecordContentChunksCommand
from telegram_agent.core.content_processing.common.types import ContentChunkType
from telegram_agent.core.content_processing.db.models.content_processing import ContentChunk


class SyncSqlAlchemyContentChunkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count_for_job(
        self,
        *,
        job_id: UUID,
        content_type: ContentChunkType = ContentChunkType.TRANSCRIPT,
    ) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(ContentChunk)
                .where(
                    ContentChunk.job_id == job_id,
                    ContentChunk.content_type == content_type,
                )
            )
            or 0
        )

    def list_for_job(
        self,
        *,
        job_id: UUID,
        content_type: ContentChunkType = ContentChunkType.TRANSCRIPT,
    ) -> list[ContentChunk]:
        return list(
            self._session.scalars(
                select(ContentChunk)
                .where(
                    ContentChunk.job_id == job_id,
                    ContentChunk.content_type == content_type,
                )
                .order_by(ContentChunk.chunk_index)
            )
        )

    def record(self, command: RecordContentChunksCommand) -> bool:
        content_type = ContentChunkType(command.content_type)
        if self.count_for_job(job_id=command.job_id, content_type=content_type) > 0:
            return True

        for chunk in command.chunks:
            speakers = list(chunk.speakers) if chunk.speakers else None
            self._session.add(
                ContentChunk(
                    job_id=command.job_id,
                    content_type=content_type,
                    chunk_index=chunk.chunk_index,
                    text=chunk.text,
                    start_ms=chunk.start_ms,
                    end_ms=chunk.end_ms,
                    char_count=chunk.char_count,
                    token_count=chunk.token_count,
                    segment_index_start=chunk.segment_index_start,
                    segment_index_end=chunk.segment_index_end,
                    speakers=speakers,
                    strategy=chunk.strategy,
                    chunk_metadata=chunk.metadata,
                )
            )
        self._session.flush()
        return True
