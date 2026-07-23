from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import (
    EmbeddingResponseError,
    EmbeddingServiceError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.const import (
    DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
)
from telegram_agent.core.content_processing.common.results import (
    EmbeddingChunkInput,
    EmbeddingItemResult,
    EmbeddingResult,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    ContentChunkType,
    JobKind,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    ChunkEmbedding,
    ContentChunk,
    Job,
    OutboxEvent,
    TelegramSource,
)
from telegram_agent.core.content_processing.services.sync_embedding_service import (
    SyncEmbeddingService,
)


def _vector(seed: float = 0.01) -> tuple[float, ...]:
    dim = DEFAULT_EMBEDDING_VECTOR_DIMENSIONS
    return tuple(seed + (i * 0.0001) for i in range(dim))


def test_embedding_service_persists_vectors_and_finishes_job(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id, chunk_id = _seed_chunked_job(content_sync_sessionmaker)
    vector = _vector()

    class FakeClient:
        def embed_chunks(
            self,
            *,
            chunks: tuple[EmbeddingChunkInput, ...],
            model: str | None = None,
            dimensions: int | None = None,
        ) -> EmbeddingResult:
            assert len(chunks) == 1
            assert chunks[0].chunk_id == str(chunk_id)
            return EmbeddingResult(
                provider="openai",
                model="text-embedding-3-small",
                dimensions=DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
                count=1,
                embeddings=(
                    EmbeddingItemResult(
                        chunk_id=str(chunk_id),
                        index=0,
                        embedding=vector,
                        dimensions=DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
                    ),
                ),
            )

    result = SyncEmbeddingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        embedding_client=FakeClient(),  # type: ignore[arg-type]
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        emb_count = session.scalar(
            select(func.count())
            .select_from(ChunkEmbedding)
            .where(ChunkEmbedding.job_id == job_id)
        )
        row = session.scalar(
            select(ChunkEmbedding).where(ChunkEmbedding.job_id == job_id)
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert job is not None and job.status == JobStatus.EMBEDDED
    assert emb_count == 1
    assert row is not None
    assert row.chunk_id == chunk_id
    assert row.provider == "openai"
    assert row.dimensions == DEFAULT_EMBEDDING_VECTOR_DIMENSIONS
    assert len(row.embedding) == DEFAULT_EMBEDDING_VECTOR_DIMENSIONS
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]


def test_embedding_service_retryable_on_service_error(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id, _ = _seed_chunked_job(content_sync_sessionmaker)

    class FakeClient:
        def embed_chunks(self, **_kwargs):
            raise EmbeddingServiceError("temporary")

    result = SyncEmbeddingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        embedding_client=FakeClient(),  # type: ignore[arg-type]
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)

    assert result.retryable is True
    assert job is not None and job.status == JobStatus.CHUNKED


def test_embedding_service_permanent_failure(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id, _ = _seed_chunked_job(content_sync_sessionmaker)

    class FakeClient:
        def embed_chunks(self, **_kwargs):
            raise EmbeddingResponseError("bad request")

    result = SyncEmbeddingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        embedding_client=FakeClient(),  # type: ignore[arg-type]
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert job is not None and job.status == JobStatus.FAILED
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]


def test_embedding_service_idempotent_when_embeddings_exist(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id, chunk_id = _seed_chunked_job(content_sync_sessionmaker)
    with content_sync_sessionmaker() as session:
        session.add(
            ChunkEmbedding(
                job_id=job_id,
                chunk_id=chunk_id,
                provider="openai",
                model="text-embedding-3-small",
                dimensions=DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
                embedding=list(_vector(0.5)),
            )
        )
        session.commit()

    called = {"value": False}

    class FakeClient:
        def embed_chunks(self, **_kwargs):
            called["value"] = True
            raise AssertionError("should not call embedding service")

    result = SyncEmbeddingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        embedding_client=FakeClient(),  # type: ignore[arg-type]
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)

    assert result.retryable is False
    assert called["value"] is False
    assert job is not None and job.status == JobStatus.EMBEDDED


def _seed_chunked_job(sessionmaker_: sessionmaker[Session]) -> tuple[UUID, UUID]:
    with sessionmaker_() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=JobStatus.CHUNKED,
            idempotency_key=str(uuid4()),
            callback_required=True,
        )
        session.add(job)
        session.flush()
        session.add(
            TelegramSource(
                job_id=job.id,
                ingress_message_id=uuid4(),
                ingress_attachment_id=uuid4(),
                telegram_user_id=1,
                telegram_file_id="file",
                telegram_file_unique_id=None,
                attachment_type=TelegramAttachmentType.VOICE,
            )
        )
        chunk = ContentChunk(
            job_id=job.id,
            content_type=ContentChunkType.TRANSCRIPT,
            chunk_index=0,
            text="hello world",
            start_ms=0,
            end_ms=1500,
            char_count=11,
            token_count=3,
            segment_index_start=0,
            segment_index_end=0,
            speakers=None,
            strategy="transcript_segment_window_v1",
        )
        session.add(chunk)
        session.commit()
        return job.id, chunk.id
