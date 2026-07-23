from __future__ import annotations

from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import (
    ChunkingResponseError,
    ChunkingServiceError,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.results import (
    ChunkingResult,
    ChunkResultItem,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    ContentChunkType,
    JobKind,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    ContentChunk,
    Job,
    OutboxEvent,
    TelegramSource,
    Transcript,
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services import sync_chunking_service
from telegram_agent.core.content_processing.services.sync_chunking_service import (
    SyncChunkingService,
)


def test_chunking_service_persists_chunks_and_enqueues_embedding(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_transcribed_job(content_sync_sessionmaker)

    class FakeChunkingClient:
        def __init__(self, _settings) -> None:
            pass

        def chunk_transcript(self, **_kwargs) -> ChunkingResult:
            return ChunkingResult(
                content_type=ContentChunkType.TRANSCRIPT.value,
                strategy="transcript_segment_window_v1",
                chunk_count=1,
                chunks=(
                    ChunkResultItem(
                        chunk_index=0,
                        text="hello world",
                        start_ms=0,
                        end_ms=1500,
                        char_count=11,
                        token_count=3,
                        segment_index_start=0,
                        segment_index_end=0,
                        speakers=(),
                    ),
                ),
            )

    monkeypatch.setattr(sync_chunking_service, "ChunkingClient", FakeChunkingClient)
    result = SyncChunkingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        chunk_count = session.scalar(
            select(func.count())
            .select_from(ContentChunk)
            .where(ContentChunk.job_id == job_id)
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert job is not None and job.status == JobStatus.CHUNKED
    assert chunk_count == 1
    assert [event.event_type for event in events] == [
        OutboxEventType.CHUNKS_READY_FOR_EMBEDDING.value
    ]


def test_chunking_service_retryable_on_service_error(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_transcribed_job(content_sync_sessionmaker)

    class FakeChunkingClient:
        def __init__(self, _settings) -> None:
            pass

        def chunk_transcript(self, **_kwargs):
            raise ChunkingServiceError("temporary")

    monkeypatch.setattr(sync_chunking_service, "ChunkingClient", FakeChunkingClient)
    result = SyncChunkingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)

    assert result.retryable is True
    assert job is not None and job.status == JobStatus.TRANSCRIBED


def test_chunking_service_permanent_failure(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_transcribed_job(content_sync_sessionmaker)

    class FakeChunkingClient:
        def __init__(self, _settings) -> None:
            pass

        def chunk_transcript(self, **_kwargs):
            raise ChunkingResponseError("bad request")

    monkeypatch.setattr(sync_chunking_service, "ChunkingClient", FakeChunkingClient)
    result = SyncChunkingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
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


def test_chunking_service_idempotent_when_chunks_exist(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_transcribed_job(content_sync_sessionmaker)
    with content_sync_sessionmaker() as session:
        session.add(
            ContentChunk(
                job_id=job_id,
                content_type=ContentChunkType.TRANSCRIPT,
                chunk_index=0,
                text="existing",
                start_ms=0,
                end_ms=100,
                char_count=8,
                token_count=2,
                segment_index_start=0,
                segment_index_end=0,
                speakers=None,
                strategy="transcript_segment_window_v1",
            )
        )
        session.commit()

    called = {"value": False}

    class FakeChunkingClient:
        def __init__(self, _settings) -> None:
            pass

        def chunk_transcript(self, **_kwargs):
            called["value"] = True
            raise AssertionError("should not call chunking service")

    monkeypatch.setattr(sync_chunking_service, "ChunkingClient", FakeChunkingClient)
    result = SyncChunkingService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert called["value"] is False
    assert job is not None and job.status == JobStatus.CHUNKED
    assert [event.event_type for event in events] == [
        OutboxEventType.CHUNKS_READY_FOR_EMBEDDING.value
    ]


def _seed_transcribed_job(sessionmaker_: sessionmaker[Session]):
    with sessionmaker_() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=JobStatus.TRANSCRIBED,
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
                telegram_file_id="file-id",
                telegram_file_unique_id=None,
                attachment_type=TelegramAttachmentType.VOICE,
            )
        )
        transcript = Transcript(
            job_id=job.id,
            text="hello world",
            language="en",
            language_probability=0.9,
            duration_ms=1500,
        )
        session.add(transcript)
        session.flush()
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                segment_index=0,
                start_ms=0,
                end_ms=1500,
                text="hello world",
                language="en",
                language_probability=0.9,
                speaker=None,
                speaker_confidence=None,
            )
        )
        session.commit()
        return job.id
