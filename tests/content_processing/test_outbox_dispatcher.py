from __future__ import annotations

from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.celery.tasks.media_download import download_telegram_media_task
from telegram_agent.core.content_processing.common.types import (
    JobKind,
    JobStatus,
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import Job, OutboxEvent
from telegram_agent.core.content_processing.services.outbox_dispatcher import OutboxDispatcher


def test_successful_celery_publication_marks_event_published(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id, event_id = _seed_job_and_event(content_sync_sessionmaker)
    published_args: list[tuple[str]] = []

    def fake_apply_async(*, args, **kwargs) -> None:
        published_args.append(args)

    monkeypatch.setattr(download_telegram_media_task, "apply_async", fake_apply_async)

    result = _dispatcher(content_sync_uow_factory).dispatch_once()

    with content_sync_sessionmaker() as session:
        event = session.get(OutboxEvent, event_id)

    assert result.claimed == 1
    assert result.published == 1
    assert published_args == [(str(job_id),)]
    assert event is not None
    assert event.status == OutboxEventStatus.PUBLISHED
    assert event.published_at is not None


def test_celery_publication_failure_leaves_event_retryable(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    _, event_id = _seed_job_and_event(content_sync_sessionmaker)
    before_dispatch = utcnow()

    def failing_apply_async(*, args, **kwargs) -> None:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(download_telegram_media_task, "apply_async", failing_apply_async)

    result = _dispatcher(content_sync_uow_factory).dispatch_once()

    with content_sync_sessionmaker() as session:
        event = session.get(OutboxEvent, event_id)

    assert result.claimed == 1
    assert result.retryable_failures == 1
    assert event is not None
    assert event.status == OutboxEventStatus.PENDING
    assert event.attempt_count == 1
    assert event.available_at > before_dispatch
    assert event.last_error == "redis unavailable"


def test_unsupported_event_type_is_marked_failed_without_publishing(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    _, event_id = _seed_job_and_event(content_sync_sessionmaker, event_type="future.event")
    published = False

    def fake_apply_async(*, args, **kwargs) -> None:
        nonlocal published
        published = True

    monkeypatch.setattr(download_telegram_media_task, "apply_async", fake_apply_async)

    result = _dispatcher(content_sync_uow_factory).dispatch_once()

    with content_sync_sessionmaker() as session:
        event = session.get(OutboxEvent, event_id)

    assert result.claimed == 1
    assert result.permanent_failures == 1
    assert published is False
    assert event is not None
    assert event.status == OutboxEventStatus.FAILED
    assert event.attempt_count == 1
    assert event.last_error == "Unsupported outbox event type: future.event"


def _dispatcher(content_sync_uow_factory) -> OutboxDispatcher:
    return OutboxDispatcher(
        uow_factory=content_sync_uow_factory,
        batch_size=10,
        lease_timeout=timedelta(minutes=1),
        retry_base_delay=timedelta(seconds=5),
        retry_max_delay=timedelta(minutes=5),
        lease_owner="test-dispatcher",
    )


def _seed_job_and_event(
    content_sync_sessionmaker: sessionmaker[Session],
    *,
    event_type: str = OutboxEventType.CONTENT_PROCESSING_JOB_READY.value,
) -> tuple[UUID, UUID]:
    with content_sync_sessionmaker() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=JobStatus.QUEUED,
            idempotency_key=f"dispatcher-job-{uuid4()}",
            callback_required=True,
        )
        session.add(job)
        session.flush()
        event = OutboxEvent(
            event_type=event_type,
            job_id=job.id,
            idempotency_key=f"{event_type}:{job.id}",
            payload={},
            status=OutboxEventStatus.PENDING,
            available_at=utcnow() - timedelta(seconds=1),
        )
        session.add(event)
        session.commit()
        return job.id, event.id


def test_transcription_event_is_published_to_generic_transcription_task(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    from telegram_agent.core.content_processing.celery.tasks.transcription import transcribe_media_task

    job_id, event_id = _seed_job_and_event(
        content_sync_sessionmaker,
        event_type=OutboxEventType.MEDIA_READY_FOR_TRANSCRIPTION.value,
    )
    published_args: list[tuple[str]] = []

    def fake_apply_async(*, args, **kwargs) -> None:
        published_args.append(args)

    monkeypatch.setattr(transcribe_media_task, "apply_async", fake_apply_async)
    result = _dispatcher(content_sync_uow_factory).dispatch_once()

    with content_sync_sessionmaker() as session:
        event = session.get(OutboxEvent, event_id)
    assert result.published == 1
    assert published_args == [(str(job_id),)]
    assert event is not None and event.status == OutboxEventStatus.PUBLISHED
