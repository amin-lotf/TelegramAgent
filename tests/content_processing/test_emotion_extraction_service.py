from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.results import (
    EmotionExtractionBatchResult,
    SegmentEmotionUpdate,
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
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services import sync_emotion_extraction_service
from telegram_agent.core.content_processing.services.sync_emotion_extraction_service import (
    SyncEmotionExtractionService,
)


def test_emotion_extraction_updates_segments_and_finishes_job(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    job_id = _seed_transcribed_job(
        content_sync_sessionmaker,
        local_path=str(audio_path),
        segments=((0, 0, 1000, "hello"), (1, 1000, 2000, "world")),
    )

    clip_calls: list[tuple[int, int]] = []
    emotion_calls: list[str] = []

    class FakeAudioClipper:
        def __init__(self, *args, **kwargs) -> None:
            pass

        @classmethod
        def from_settings(cls, _settings):
            return cls()

        def clip_path_for_segment(self, *, job_id: UUID, segment_index: int) -> Path:
            path = tmp_path / "clips" / f"segment_{segment_index}.ogg"
            path.parent.mkdir(parents=True, exist_ok=True)
            return path

        def extract_clip(self, *, source_path, start_ms, end_ms, dest_path):
            clip_calls.append((start_ms, end_ms))
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_bytes(b"clip")
            return dest_path

    class FakeSenseVoiceClient:
        def __init__(self, _settings) -> None:
            pass

        def extract_emotions(self, *, manifest_path, request_id, timeout_seconds, heartbeat):
            del request_id, timeout_seconds
            heartbeat()
            emotion_calls.append(str(manifest_path))
            return EmotionExtractionBatchResult(
                segments=(
                    SegmentEmotionUpdate(0, "HAPPY", ("Speech",)),
                    SegmentEmotionUpdate(1, "NEUTRAL", ("Speech",)),
                )
            )

    monkeypatch.setattr(
        sync_emotion_extraction_service,
        "AudioClipper",
        FakeAudioClipper,
    )
    monkeypatch.setattr(
        sync_emotion_extraction_service,
        "SenseVoiceClient",
        FakeSenseVoiceClient,
    )

    test_settings = settings.model_copy(
        update={"media_storage_root": str(tmp_path)}
    )
    result = SyncEmotionExtractionService(
        uow_factory=content_sync_uow_factory,
        settings=test_settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        segments = list(
            session.scalars(
                select(TranscriptSegment)
                .join(Transcript)
                .where(Transcript.job_id == job_id)
                .order_by(TranscriptSegment.segment_index)
            )
        )
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert result.error_message is None
    assert job is not None and job.status == JobStatus.EMOTION_EXTRACTED
    assert clip_calls == [(0, 1000), (1000, 2000)]
    assert len(emotion_calls) == 1
    assert segments[0].emotion == "HAPPY"
    assert segments[0].audio_events == ["Speech"]
    assert segments[1].emotion == "NEUTRAL"
    assert segments[1].audio_events == ["Speech"]
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]


def test_emotion_extraction_empty_transcript_completes_without_client(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.ogg"
    audio_path.write_bytes(b"fake-audio")
    job_id = _seed_transcribed_job(
        content_sync_sessionmaker,
        local_path=str(audio_path),
        segments=(),
    )

    class BoomClient:
        def __init__(self, _settings) -> None:
            raise AssertionError("SenseVoice client should not be used")

    monkeypatch.setattr(
        sync_emotion_extraction_service,
        "SenseVoiceClient",
        BoomClient,
    )

    result = SyncEmotionExtractionService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
    ).execute(job_id=job_id, retry_count=0)

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        events = list(
            session.scalars(select(OutboxEvent).where(OutboxEvent.job_id == job_id))
        )

    assert result.retryable is False
    assert job is not None and job.status == JobStatus.EMOTION_EXTRACTED
    assert [event.event_type for event in events] == [
        OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value
    ]


def test_emotion_extraction_missing_audio_fails_permanently(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_transcribed_job(
        content_sync_sessionmaker,
        local_path=None,
        segments=((0, 0, 500, "hi"),),
    )

    result = SyncEmotionExtractionService(
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


def _seed_transcribed_job(
    sessionmaker_: sessionmaker[Session],
    *,
    local_path: str | None,
    segments: tuple[tuple[int, int, int, str], ...],
) -> UUID:
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
            MediaAsset(
                job_id=job.id,
                role=MediaAssetRole.SOURCE,
                parent_asset_id=None,
                media_type=TelegramAttachmentType.VOICE.value,
                local_path=local_path,
                mime_type="audio/ogg",
                duration_ms=2000,
                size_bytes=17,
            )
        )
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
            text=" ".join(text for *_rest, text in segments) or "",
            language="en",
            language_probability=0.9,
            duration_ms=2000,
        )
        session.add(transcript)
        session.flush()
        for segment_index, start_ms, end_ms, text in segments:
            session.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    segment_index=segment_index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    text=text,
                    language="en",
                    language_probability=0.9,
                    speaker=None,
                    speaker_confidence=None,
                )
            )
        session.commit()
        return job.id
