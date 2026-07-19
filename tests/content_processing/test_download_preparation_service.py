from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    DownloadMediaType,
    JobKind,
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    Job,
    MediaAsset,
    OutboxEvent,
    TelegramSource,
    Transcript,
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitlePreparationService,
)
from telegram_agent.core.content_processing.services.sync_download_preparation_service import (
    SyncDownloadPreparationService,
)


def test_video_preparation_sets_final_path_and_delivery_outbox(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
    monkeypatch,
) -> None:
    ingress_message_id = uuid4()
    source_job_id = _seed_source_video_job(
        content_sync_sessionmaker,
        ingress_message_id=ingress_message_id,
        media_root=tmp_path,
    )
    prep_job_id = _seed_download_request_job(
        content_sync_sessionmaker,
        media_type=DownloadMediaType.VIDEO.value,
        media_ingress_message_id=ingress_message_id,
        requested_subtitle_language="en",
    )

    muxed_path = tmp_path / str(prep_job_id) / "vtest123456.mkv"
    muxed_path.parent.mkdir(parents=True, exist_ok=True)
    muxed_path.write_bytes(b"muxed-video")

    class FakeMux:
        def mux(self, *, job_id, video_path, audio_path, subtitle_path):
            assert job_id == prep_job_id
            assert Path(video_path).is_file()
            assert Path(audio_path).is_file()
            assert Path(subtitle_path).is_file()
            assert Path(subtitle_path).read_text(encoding="utf-8")
            return str(muxed_path)

    service = SyncDownloadPreparationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        subtitle_service=SubtitlePreparationService(storage_root=tmp_path),
        mux_service=FakeMux(),  # type: ignore[arg-type]
    )
    result = service.execute(job_id=prep_job_id, retry_count=0)

    assert result.retryable is False
    assert result.error_message is None

    with content_sync_sessionmaker() as session:
        job = session.get(Job, prep_job_id)
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == prep_job_id)
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.job_id == prep_job_id)
            )
        )

    assert job is not None
    assert job.status == JobStatus.COMPLETED
    assert request is not None
    assert request.final_path == str(muxed_path)
    assert any(
        event.event_type == OutboxEventType.DOWNLOAD_READY_FOR_DELIVERY.value
        for event in events
    )
    assert source_job_id is not None


def test_preparation_retries_while_source_transcript_not_ready(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    """Handoff often arrives while the attachment job is still transcribing."""
    ingress_message_id = uuid4()
    source_job_id = uuid4()
    video_path = tmp_path / "video.mp4"
    audio_path = tmp_path / "audio.ogg"
    video_path.write_bytes(b"video-bytes")
    audio_path.write_bytes(b"audio-bytes")

    with content_sync_sessionmaker() as session:
        session.add(
            Job(
                id=source_job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=JobStatus.TRANSCRIBING,
                idempotency_key=f"source-pending-{source_job_id}",
                callback_required=True,
            )
        )
        session.flush()
        session.add(
            TelegramSource(
                job_id=source_job_id,
                ingress_message_id=ingress_message_id,
                ingress_attachment_id=uuid4(),
                telegram_user_id=1,
                telegram_file_id="file",
                attachment_type=TelegramAttachmentType.VIDEO,
            )
        )
        source_asset_id = uuid4()
        session.add(
            MediaAsset(
                id=source_asset_id,
                job_id=source_job_id,
                role=MediaAssetRole.SOURCE,
                local_path=str(tmp_path / "source.mp4"),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=10,
            )
        )
        session.add(
            MediaAsset(
                job_id=source_job_id,
                role=MediaAssetRole.VIDEO,
                parent_asset_id=source_asset_id,
                local_path=str(video_path),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=video_path.stat().st_size,
            )
        )
        session.add(
            MediaAsset(
                job_id=source_job_id,
                role=MediaAssetRole.AUDIO,
                parent_asset_id=source_asset_id,
                local_path=str(audio_path),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=audio_path.stat().st_size,
            )
        )
        session.commit()

    prep_job_id = _seed_download_request_job(
        content_sync_sessionmaker,
        media_type=DownloadMediaType.VIDEO.value,
        media_ingress_message_id=ingress_message_id,
    )

    result = SyncDownloadPreparationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=prep_job_id, retry_count=0)

    assert result.retryable is True
    assert result.error_message is not None
    assert "waiting" in result.error_message.lower()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, prep_job_id)
    assert job is not None
    assert job.status == JobStatus.QUEUED


def test_audio_preparation_uses_source_asset_path(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    ingress_message_id = uuid4()
    audio_path = tmp_path / "source.ogg"
    audio_path.write_bytes(b"audio-bytes")
    _seed_source_audio_job(
        content_sync_sessionmaker,
        ingress_message_id=ingress_message_id,
        local_path=str(audio_path),
    )
    prep_job_id = _seed_download_request_job(
        content_sync_sessionmaker,
        media_type=DownloadMediaType.AUDIO.value,
        media_ingress_message_id=ingress_message_id,
    )

    result = SyncDownloadPreparationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=prep_job_id, retry_count=0)

    assert result.retryable is False
    with content_sync_sessionmaker() as session:
        job = session.get(Job, prep_job_id)
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == prep_job_id)
        )
    assert job is not None and job.status == JobStatus.COMPLETED
    assert request is not None and request.final_path == str(audio_path)


def _seed_source_video_job(
    sessionmaker_factory: sessionmaker[Session],
    *,
    ingress_message_id: UUID,
    media_root: Path,
) -> UUID:
    job_id = uuid4()
    video_path = media_root / "video.mp4"
    audio_path = media_root / "audio.ogg"
    video_path.write_bytes(b"video-bytes")
    audio_path.write_bytes(b"audio-bytes")

    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=JobStatus.COMPLETED,
                idempotency_key=f"source-{job_id}",
                callback_required=True,
            )
        )
        session.flush()
        session.add(
            TelegramSource(
                job_id=job_id,
                ingress_message_id=ingress_message_id,
                ingress_attachment_id=uuid4(),
                telegram_user_id=1,
                telegram_file_id="file",
                attachment_type=TelegramAttachmentType.VIDEO,
            )
        )
        source_asset_id = uuid4()
        session.add(
            MediaAsset(
                id=source_asset_id,
                job_id=job_id,
                role=MediaAssetRole.SOURCE,
                local_path=str(media_root / "source.mp4"),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=10,
            )
        )
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.VIDEO,
                parent_asset_id=source_asset_id,
                local_path=str(video_path),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=video_path.stat().st_size,
            )
        )
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.AUDIO,
                parent_asset_id=source_asset_id,
                local_path=str(audio_path),
                media_type=TelegramAttachmentType.VIDEO.value,
                size_bytes=audio_path.stat().st_size,
            )
        )
        transcript_id = uuid4()
        session.add(
            Transcript(
                id=transcript_id,
                job_id=job_id,
                text="Hello world",
                language="en",
                language_probability=0.99,
                duration_ms=2000,
            )
        )
        session.flush()
        session.add(
            TranscriptSegment(
                transcript_id=transcript_id,
                segment_index=0,
                start_ms=0,
                end_ms=1500,
                text="Hello world",
                language="en",
            )
        )
        session.commit()
    return job_id


def _seed_source_audio_job(
    sessionmaker_factory: sessionmaker[Session],
    *,
    ingress_message_id: UUID,
    local_path: str,
) -> UUID:
    job_id = uuid4()
    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=JobStatus.COMPLETED,
                idempotency_key=f"source-audio-{job_id}",
                callback_required=True,
            )
        )
        session.flush()
        session.add(
            TelegramSource(
                job_id=job_id,
                ingress_message_id=ingress_message_id,
                ingress_attachment_id=uuid4(),
                telegram_user_id=1,
                telegram_file_id="file",
                attachment_type=TelegramAttachmentType.AUDIO,
            )
        )
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.SOURCE,
                local_path=local_path,
                media_type=TelegramAttachmentType.AUDIO.value,
                size_bytes=11,
            )
        )
        session.commit()
    return job_id


def _seed_download_request_job(
    sessionmaker_factory: sessionmaker[Session],
    *,
    media_type: str,
    media_ingress_message_id: UUID,
    requested_subtitle_language: str | None = None,
) -> UUID:
    job_id = uuid4()
    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.DOWNLOAD_PREPARATION,
                status=JobStatus.QUEUED,
                idempotency_key=f"prep-{job_id}",
                callback_required=False,
            )
        )
        session.flush()
        session.add(
            DownloadRequest(
                job_id=job_id,
                chat_id=99,
                telegram_user_id=100,
                group_id=uuid4(),
                agent_message_id=uuid4(),
                media_ingress_message_id=media_ingress_message_id,
                media_type=media_type,
                requested_subtitle_language=requested_subtitle_language,
                assistant_text="Here you go",
            )
        )
        session.commit()
    return job_id
