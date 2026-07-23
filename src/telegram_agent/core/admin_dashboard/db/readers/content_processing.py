"""SELECT-only queries against the content-processing database."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.admin_dashboard.db.mappings import content_processing as tables
from telegram_agent.core.admin_dashboard.services.view_models import (
    ChunkEmbeddingRow,
    ContentChunkRow,
    JobRow,
    MediaAssetRow,
    OutboxRow,
    TelegramSourceRow,
    TranscriptRow,
    TranscriptSegmentRow,
)

_EMBEDDING_PREVIEW_DIMS = 4


class ContentProcessingReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_source_by_ingress_message_id(
        self,
        ingress_message_id: UUID,
    ) -> TelegramSourceRow | None:
        tbl = tables.telegram_sources
        result = await self._session.execute(
            select(tbl).where(tbl.c.ingress_message_id == ingress_message_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return TelegramSourceRow(
            id=row.id,
            job_id=row.job_id,
            ingress_message_id=row.ingress_message_id,
            ingress_attachment_id=row.ingress_attachment_id,
            telegram_user_id=row.telegram_user_id,
            telegram_file_id=row.telegram_file_id,
            telegram_file_unique_id=row.telegram_file_unique_id,
            attachment_type=row.attachment_type,
        )

    async def get_job(self, job_id: UUID) -> JobRow | None:
        tbl = tables.jobs
        result = await self._session.execute(select(tbl).where(tbl.c.id == job_id))
        row = result.one_or_none()
        if row is None:
            return None
        return JobRow(
            id=row.id,
            kind=row.kind,
            status=row.status,
            idempotency_key=row.idempotency_key,
            error_message=row.error_message,
            callback_required=row.callback_required,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_assets(self, job_id: UUID) -> list[MediaAssetRow]:
        tbl = tables.media_assets
        result = await self._session.execute(
            select(tbl).where(tbl.c.job_id == job_id).order_by(tbl.c.role)
        )
        return [
            MediaAssetRow(
                id=row.id,
                job_id=row.job_id,
                role=row.role,
                parent_asset_id=row.parent_asset_id,
                local_path=row.local_path,
                media_type=row.media_type,
                mime_type=row.mime_type,
                duration_ms=row.duration_ms,
                size_bytes=row.size_bytes,
            )
            for row in result
        ]

    async def list_outbox(self, job_id: UUID) -> list[OutboxRow]:
        tbl = tables.outbox_events
        result = await self._session.execute(
            select(tbl)
            .where(tbl.c.job_id == job_id)
            .order_by(tbl.c.created_at.asc(), tbl.c.id.asc())
        )
        return [
            OutboxRow(
                id=row.id,
                event_type=row.event_type,
                status=row.status,
                attempt_count=row.attempt_count,
                created_at=row.created_at,
                published_at=row.published_at,
                available_at=row.available_at,
                locked_at=row.locked_at,
                locked_by=row.locked_by,
                last_error=row.last_error,
                idempotency_key=row.idempotency_key,
                payload=dict(row.payload or {}),
                job_id=row.job_id,
            )
            for row in result
        ]

    async def get_transcript(self, job_id: UUID) -> TranscriptRow | None:
        t = tables.transcripts
        s = tables.transcript_segments
        result = await self._session.execute(select(t).where(t.c.job_id == job_id))
        row = result.one_or_none()
        if row is None:
            return None
        seg_result = await self._session.execute(
            select(s)
            .where(s.c.transcript_id == row.id)
            .order_by(s.c.segment_index.asc())
        )
        segments = tuple(
            TranscriptSegmentRow(
                id=seg.id,
                transcript_id=seg.transcript_id,
                segment_index=seg.segment_index,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                language=seg.language,
                language_probability=seg.language_probability,
                speaker=seg.speaker,
                speaker_confidence=seg.speaker_confidence,
            )
            for seg in seg_result
        )
        return TranscriptRow(
            id=row.id,
            job_id=row.job_id,
            text=row.text,
            language=row.language,
            language_probability=row.language_probability,
            duration_ms=row.duration_ms,
            segments=segments,
        )

    async def list_chunks(self, job_id: UUID) -> list[ContentChunkRow]:
        tbl = tables.content_chunks
        result = await self._session.execute(
            select(tbl)
            .where(tbl.c.job_id == job_id)
            .order_by(tbl.c.chunk_index.asc())
        )
        chunks: list[ContentChunkRow] = []
        for row in result:
            speakers_raw = row.speakers
            speakers: tuple[str, ...] | None
            if speakers_raw is None:
                speakers = None
            elif isinstance(speakers_raw, list):
                speakers = tuple(str(item) for item in speakers_raw)
            else:
                speakers = (str(speakers_raw),)
            chunks.append(
                ContentChunkRow(
                    id=row.id,
                    job_id=row.job_id,
                    content_type=row.content_type,
                    chunk_index=row.chunk_index,
                    text=row.text,
                    start_ms=row.start_ms,
                    end_ms=row.end_ms,
                    char_count=row.char_count,
                    token_count=row.token_count,
                    segment_index_start=row.segment_index_start,
                    segment_index_end=row.segment_index_end,
                    speakers=speakers,
                    strategy=row.strategy,
                    created_at=row.created_at,
                )
            )
        return chunks

    async def list_embeddings(self, job_id: UUID) -> list[ChunkEmbeddingRow]:
        emb = tables.chunk_embeddings
        chunks = tables.content_chunks
        result = await self._session.execute(
            select(
                emb.c.id,
                emb.c.job_id,
                emb.c.chunk_id,
                emb.c.provider,
                emb.c.model,
                emb.c.dimensions,
                emb.c.embedding,
                emb.c.created_at,
                chunks.c.chunk_index,
            )
            .select_from(
                emb.outerjoin(chunks, chunks.c.id == emb.c.chunk_id)
            )
            .where(emb.c.job_id == job_id)
            .order_by(chunks.c.chunk_index.asc().nulls_last(), emb.c.created_at.asc())
        )
        rows: list[ChunkEmbeddingRow] = []
        for row in result:
            raw = row.embedding
            preview: tuple[float, ...]
            if isinstance(raw, list):
                preview = tuple(float(value) for value in raw[:_EMBEDDING_PREVIEW_DIMS])
            else:
                preview = ()
            rows.append(
                ChunkEmbeddingRow(
                    id=row.id,
                    job_id=row.job_id,
                    chunk_id=row.chunk_id,
                    chunk_index=row.chunk_index,
                    provider=row.provider,
                    model=row.model,
                    dimensions=row.dimensions,
                    embedding_preview=preview,
                    created_at=row.created_at,
                )
            )
        return rows

    async def list_job_status_by_ingress_ids(
        self,
        ingress_ids: list[UUID],
    ) -> dict[UUID, str]:
        if not ingress_ids:
            return {}
        src = tables.telegram_sources
        jobs = tables.jobs
        result = await self._session.execute(
            select(src.c.ingress_message_id, jobs.c.status)
            .select_from(src.join(jobs, jobs.c.id == src.c.job_id))
            .where(src.c.ingress_message_id.in_(ingress_ids))
        )
        return {row.ingress_message_id: row.status for row in result}
