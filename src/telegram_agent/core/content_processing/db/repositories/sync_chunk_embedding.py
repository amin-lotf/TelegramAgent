from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.common.commands import RecordChunkEmbeddingsCommand
from telegram_agent.core.content_processing.common.const import (
    DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
)
from telegram_agent.core.content_processing.db.models.content_processing import ChunkEmbedding


class SyncSqlAlchemyChunkEmbeddingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def count_for_job(self, *, job_id: UUID) -> int:
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(ChunkEmbedding)
                .where(ChunkEmbedding.job_id == job_id)
            )
            or 0
        )

    def list_for_job(self, *, job_id: UUID) -> list[ChunkEmbedding]:
        return list(
            self._session.scalars(
                select(ChunkEmbedding)
                .where(ChunkEmbedding.job_id == job_id)
                .order_by(ChunkEmbedding.created_at.asc())
            )
        )

    def record(self, command: RecordChunkEmbeddingsCommand) -> bool:
        if self.count_for_job(job_id=command.job_id) > 0:
            return True

        for item in command.embeddings:
            if item.dimensions != DEFAULT_EMBEDDING_VECTOR_DIMENSIONS:
                return False
            if len(item.embedding) != DEFAULT_EMBEDDING_VECTOR_DIMENSIONS:
                return False
            self._session.add(
                ChunkEmbedding(
                    job_id=command.job_id,
                    chunk_id=item.chunk_id,
                    provider=item.provider,
                    model=item.model,
                    dimensions=item.dimensions,
                    embedding=list(item.embedding),
                )
            )
        self._session.flush()
        return True
