from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.results import (
    MediaDemuxResult,
    MediaDownloadResult,
    TranscriptionResult,
    TranscriptionSegmentResult,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    JobKind,
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    Job,
    MediaAsset,
    OutboxEvent,
    TelegramSource,
    Transcript,
)
from telegram_agent.core.content_processing.services import sync_transcription_service
from telegram_agent.core.content_processing.services import sync_telegram_media_download
from telegram_agent.core.content_processing.services.sync_telegram_media_download import (
    SyncTelegramMediaDownloadService,
)
from telegram_agent.core.content_processing.services.sync_transcription_service import (
    SyncTranscriptionService,
)


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
    _stub_media_demuxer(monkeypatch, asset_id)

    result = SyncTelegramMediaDownloadService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        asset = session.get(MediaAsset, asset_id)
        assets = list(
            session.scalars(select(MediaAsset).where(MediaAsset.job_id == job_id))
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )
    assert result.retryable is False
    assert job is not None and job.status == JobStatus.DOWNLOADED
    assert asset is not None and asset.size_bytes == 17
    assert asset.role == MediaAssetRole.SOURCE
    assert [event.event_type for event in events] == [
        OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value
    ]
    assert events[0].idempotency_key == (
        f"{OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value}:{job_id}"
    )
    assert events[0].payload == {}

    if attachment_type in (
        TelegramAttachmentType.VIDEO,
        TelegramAttachmentType.VIDEO_NOTE,
    ):
        roles = {item.role for item in assets}
        assert roles == {
            MediaAssetRole.SOURCE,
            MediaAssetRole.AUDIO,
            MediaAssetRole.VIDEO,
        }
        audio = next(item for item in assets if item.role == MediaAssetRole.AUDIO)
        video = next(item for item in assets if item.role == MediaAssetRole.VIDEO)
        assert audio.parent_asset_id == asset_id
        assert video.parent_asset_id == asset_id
        assert audio.local_path is not None
        assert video.local_path is not None
    else:
        assert len(assets) == 1


def test_non_transcribable_download_creates_completion_event(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id, asset_id = _seed_job(
        content_sync_sessionmaker, TelegramAttachmentType.DOCUMENT
    )

    class FakeTelegramMediaDownloader:
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, _context):
            # Plain document (not a video/audio container) completes without
            # demux/transcription.
            return MediaDownloadResult(f"/tmp/{asset_id}.pdf", 17, "application/pdf")

    monkeypatch.setattr(
        sync_telegram_media_download,
        "TelegramMediaDownloader",
        FakeTelegramMediaDownloader,
    )

    SyncTelegramMediaDownloadService(
        uow_factory=content_sync_uow_factory, settings=settings
    ).execute(
        job_id=job_id,
        retry_count=0,
    )

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )
    assert job is not None and job.status == JobStatus.COMPLETED
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]
    assert events[0].payload == {}


def test_video_document_download_demuxes_and_queues_transcription(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    """MKV/etc. sent as Telegram document still demux + transcribe."""
    job_id, asset_id = _seed_job(
        content_sync_sessionmaker, TelegramAttachmentType.DOCUMENT
    )

    class FakeTelegramMediaDownloader:
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, _context):
            return MediaDownloadResult(
                f"/tmp/{asset_id}.mkv",
                100,
                "video/x-matroska",
            )

    monkeypatch.setattr(
        sync_telegram_media_download,
        "TelegramMediaDownloader",
        FakeTelegramMediaDownloader,
    )
    _stub_media_demuxer(monkeypatch, asset_id)

    result = SyncTelegramMediaDownloadService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        assets = list(
            session.scalars(select(MediaAsset).where(MediaAsset.job_id == job_id))
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert job is not None and job.status == JobStatus.DOWNLOADED
    roles = {item.role for item in assets}
    assert roles == {
        MediaAssetRole.SOURCE,
        MediaAssetRole.AUDIO,
        MediaAssetRole.VIDEO,
    }
    assert [event.event_type for event in events] == [
        OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value
    ]


def test_download_service_claims_once_and_returns_detached_source_context(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id, asset_id = _seed_job(
        content_sync_sessionmaker, TelegramAttachmentType.VOICE
    )
    contexts = []

    class FakeTelegramMediaDownloader:
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, context):
            contexts.append(context)
            return MediaDownloadResult(f"/tmp/{asset_id}.ogg", 17, "audio/ogg")

    monkeypatch.setattr(
        sync_telegram_media_download,
        "TelegramMediaDownloader",
        FakeTelegramMediaDownloader,
    )
    service = SyncTelegramMediaDownloadService(
        uow_factory=content_sync_uow_factory, settings=settings
    )
    service.execute(job_id=job_id, retry_count=0)
    service.execute(job_id=job_id, retry_count=0)

    assert len(contexts) == 1
    assert contexts[0].telegram_file_id == "file-id"
    assert contexts[0].media_asset_id == asset_id


def test_transcription_service_persists_complete_supported_result(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
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
                    TranscriptionSegmentResult(
                        0, 1500, "hello world", "en", 0.9, None, None
                    ),
                ),
            )

    monkeypatch.setattr(sync_transcription_service, "WhisperXClient", FakeWhisperXClient)
    result = SyncTranscriptionService(
        uow_factory=content_sync_uow_factory, settings=settings
    ).execute(
        job_id=job_id,
        retry_count=0,
    )

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        transcript = session.scalar(
            select(Transcript).where(Transcript.job_id == job_id)
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )
        segment_count = session.scalar(
            select(func.count())
            .select_from(Transcript)
            .join(Transcript.segments)
            .where(Transcript.job_id == job_id)
        )
    assert result.retryable is False
    assert job is not None and job.status == JobStatus.TRANSCRIBED
    assert transcript is not None and transcript.duration_ms == 1500
    assert segment_count == 1
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]
    assert events[0].idempotency_key == (
        f"{OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value}:{job_id}"
    )


def test_transcription_service_accepts_document_video_audio(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    """Video-as-document keeps media_type=document on demuxed audio assets."""
    job_id, source_id = _seed_job(
        content_sync_sessionmaker,
        TelegramAttachmentType.DOCUMENT,
        status=JobStatus.DOWNLOADED,
        local_path="/tmp/source.mkv",
    )
    with content_sync_sessionmaker() as session:
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.AUDIO,
                parent_asset_id=source_id,
                media_type=TelegramAttachmentType.DOCUMENT.value,
                local_path="/tmp/source.audio.ogg",
                mime_type="audio/ogg",
                duration_ms=None,
                size_bytes=11,
            )
        )
        session.commit()

    class FakeWhisperXClient:
        def __init__(self, _settings) -> None:
            pass

        def transcribe(self, **_kwargs):
            return TranscriptionResult(
                text="from document video",
                language="en",
                language_probability=0.9,
                duration_ms=1000,
                segments=(
                    TranscriptionSegmentResult(
                        0, 1000, "from document video", "en", 0.9, None, None
                    ),
                ),
            )

    monkeypatch.setattr(sync_transcription_service, "WhisperXClient", FakeWhisperXClient)
    result = SyncTranscriptionService(
        uow_factory=content_sync_uow_factory, settings=settings
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        transcript = session.scalar(
            select(Transcript).where(Transcript.job_id == job_id)
        )

    assert result.retryable is False
    assert result.error_message is None
    assert job is not None and job.status == JobStatus.TRANSCRIBED
    assert transcript is not None
    assert transcript.text == "from document video"


def test_transcription_service_prefers_audio_role_for_video(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id, source_id = _seed_job(
        content_sync_sessionmaker,
        TelegramAttachmentType.VIDEO,
        status=JobStatus.DOWNLOADED,
        local_path="/tmp/source.mp4",
    )
    with content_sync_sessionmaker() as session:
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.AUDIO,
                parent_asset_id=source_id,
                media_type=TelegramAttachmentType.VIDEO.value,
                local_path="/tmp/source.audio.ogg",
                mime_type="audio/ogg",
                duration_ms=None,
                size_bytes=11,
            )
        )
        session.commit()

    transcribed_paths: list[str] = []

    class FakeWhisperXClient:
        def __init__(self, _settings) -> None:
            pass

        def transcribe(self, *, path, mime_type, request_id, heartbeat=None):
            del heartbeat
            transcribed_paths.append(str(path))
            return TranscriptionResult(
                text="from audio track",
                language="en",
                language_probability=0.9,
                duration_ms=1000,
                segments=(
                    TranscriptionSegmentResult(
                        0, 1000, "from audio track", "en", 0.9, None, None
                    ),
                ),
            )

    monkeypatch.setattr(sync_transcription_service, "WhisperXClient", FakeWhisperXClient)
    result = SyncTranscriptionService(
        uow_factory=content_sync_uow_factory, settings=settings
    ).execute(job_id=job_id, retry_count=0)

    assert result.retryable is False
    assert transcribed_paths == ["/tmp/source.audio.ogg"]


def _stub_telegram_downloader(monkeypatch, asset_id: UUID) -> None:
    class FakeTelegramMediaDownloader:
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def download(self, _context):
            return MediaDownloadResult(f"/tmp/{asset_id}.ogg", 17, "audio/ogg")

    monkeypatch.setattr(
        sync_telegram_media_download,
        "TelegramMediaDownloader",
        FakeTelegramMediaDownloader,
    )


def _stub_media_demuxer(monkeypatch, asset_id: UUID) -> None:
    class FakeMediaDemuxer:
        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def demux(self, **_kwargs):
            return MediaDemuxResult(
                audio_path=f"/tmp/{asset_id}.audio.ogg",
                audio_size_bytes=11,
                audio_mime_type="audio/ogg",
                video_path=f"/tmp/{asset_id}.video.mp4",
                video_size_bytes=13,
                video_mime_type="video/mp4",
            )

    monkeypatch.setattr(sync_telegram_media_download, "MediaDemuxer", FakeMediaDemuxer)


def _seed_job(
    sessionmaker_: sessionmaker[Session],
    attachment_type: TelegramAttachmentType,
    *,
    status: JobStatus = JobStatus.QUEUED,
    local_path: str | None = None,
) -> tuple[UUID, UUID]:
    with sessionmaker_() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=status,
            idempotency_key=str(uuid4()),
            callback_required=True,
        )
        session.add(job)
        session.flush()
        asset = MediaAsset(
            job_id=job.id,
            role=MediaAssetRole.SOURCE,
            parent_asset_id=None,
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
