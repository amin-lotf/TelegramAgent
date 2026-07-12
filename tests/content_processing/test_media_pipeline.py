from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.results import (
    MediaDownloadResult,
    TranscriptionResult,
    TranscriptionSegmentResult,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import JobKind, JobStatus, OutboxEventType
from telegram_agent.core.content_processing.db.models.content_processing import (
    Job,
    MediaAsset,
    OutboxEvent,
    TelegramSource,
    Transcript,
)
from telegram_agent.core.content_processing.services import sync_transcription_service
from telegram_agent.core.content_processing.services import sync_telegram_media_download
from telegram_agent.core.content_processing.services.sync_telegram_media_download import SyncTelegramMediaDownloadService
from telegram_agent.core.content_processing.services.sync_transcription_service import SyncTranscriptionService


@pytest.mark.parametrize(
    "attachment_type",
    [
        TelegramAttachmentType.AUDIO,
        TelegramAttachmentType.VIDEO,
        TelegramAttachmentType.VIDEO_NOTE,
        TelegramAttachmentType.VOICE,
    ],
)
def test_download_service_creates_one_transcription_event(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
    attachment_type: TelegramAttachmentType,
) -> None:
    job_id, asset_id = _seed_job(content_sync_sessionmaker, attachment_type)
    _stub_telegram_downloader(monkeypatch, asset_id)

    result = SyncTelegramMediaDownloadService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        asset = session.get(MediaAsset, asset_id)
        events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id)))
    assert result.retryable is False
    assert job is not None and job.status == JobStatus.DOWNLOADED
    assert asset is not None and asset.size_bytes == 17
    assert [event.event_type for event in events] == [OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value]
    assert events[0].idempotency_key == (
        f"{OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value}:{job_id}"
    )
    assert events[0].payload == {}


def test_non_transcribable_download_creates_completion_event(
    content_sync_sessionmaker: sessionmaker[Session], content_sync_uow_factory, monkeypatch
) -> None:
    job_id, asset_id = _seed_job(content_sync_sessionmaker, TelegramAttachmentType.DOCUMENT)
    _stub_telegram_downloader(monkeypatch, asset_id)

    SyncTelegramMediaDownloadService(uow_factory=content_sync_uow_factory, settings=settings).execute(
        job_id=job_id,
        retry_count=0,
    )

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        events = list(session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id)))
    assert job is not None and job.status == JobStatus.COMPLETED
    assert [event.event_type for event in events] == [OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value]
    assert events[0].payload == {}


def test_download_service_claims_once_and_returns_detached_source_context(
    content_sync_sessionmaker: sessionmaker[Session], content_sync_uow_factory, monkeypatch
) -> None:
    job_id, asset_id = _seed_job(content_sync_sessionmaker, TelegramAttachmentType.VOICE)
    contexts = []

    class FakeTelegramMediaDownloader:
        
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, context):
            contexts.append(context)
            return MediaDownloadResult(f"/tmp/{asset_id}.ogg", 17, "audio/ogg")

    monkeypatch.setattr(sync_telegram_media_download, "TelegramMediaDownloader", FakeTelegramMediaDownloader)
    service = SyncTelegramMediaDownloadService(uow_factory=content_sync_uow_factory, settings=settings)
    service.execute(job_id=job_id, retry_count=0)
    service.execute(job_id=job_id, retry_count=0)

    assert len(contexts) == 1
    assert contexts[0].telegram_file_id == "file-id"
    assert contexts[0].media_asset_id == asset_id


def test_transcription_service_persists_complete_supported_result(
    content_sync_sessionmaker: sessionmaker[Session], content_sync_uow_factory, monkeypatch
) -> None:
    job_id, asset_id = _seed_job(
        content_sync_sessionmaker,
        TelegramAttachmentType.VOICE,
        status=JobStatus.DOWNLOADED,
        local_path="/tmp/media.ogg",
    )

    class FakeWhisperXClient:
        def __init__(self, _settings) -> None:
            pass

        def transcribe(self, **_kwargs):
            return TranscriptionResult(
                text="hello world",
                language="en",
                language_probability=0.9,
                duration_ms=1500,
                segments=(
                    TranscriptionSegmentResult(0, 1500, "hello world", "en", 0.9, None, None),
                ),
            )

    monkeypatch.setattr(sync_transcription_service, "WhisperXClient", FakeWhisperXClient)
    result = SyncTranscriptionService(uow_factory=content_sync_uow_factory, settings=settings).execute(
        job_id=job_id,
        retry_count=0,
    )

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        transcript = session.scalar(select(Transcript).where(Transcript.job_id == job_id))
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )
        segment_count = session.scalar(
            select(func.count()).select_from(Transcript).join(Transcript.segments).where(Transcript.job_id == job_id)
        )
    assert result.retryable is False
    assert job is not None and job.status == JobStatus.COMPLETED
    assert transcript is not None and transcript.duration_ms == 1500
    assert segment_count == 1
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]


def _stub_telegram_downloader(monkeypatch, asset_id: UUID) -> None:
    class FakeTelegramMediaDownloader:
        
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, _context):
            return MediaDownloadResult(f"/tmp/{asset_id}.ogg", 17, "audio/ogg")

    monkeypatch.setattr(sync_telegram_media_download, "TelegramMediaDownloader", FakeTelegramMediaDownloader)


def _seed_job(
    sessionmaker_: sessionmaker[Session],
    attachment_type: TelegramAttachmentType,
    *,
    status: JobStatus = JobStatus.QUEUED,
    local_path: str | None = None,
) -> tuple[UUID, UUID]:
    with sessionmaker_() as session:
        job = Job(kind=JobKind.TELEGRAM_ATTACHMENT, status=status, idempotency_key=str(uuid4()), callback_required=True)
        session.add(job)
        session.flush()
        asset = MediaAsset(
            job_id=job.id,
            media_type=attachment_type.value,
            local_path=local_path,
            mime_type=None,
            duration_ms=None,
            size_bytes=None,
        )
        source = TelegramSource(
            job_id=job.id,
            ingress_message_id=uuid4(),
            ingress_attachment_id=uuid4(),
            telegram_user_id=1,
            telegram_file_id="file-id",
            telegram_file_unique_id=None,
            attachment_type=attachment_type,
        )
        session.add_all((asset, source))
        session.commit()
        return job.id, asset.id
