from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.content_processing.common.commands import (
    CreateDownloadRequestCommand,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    JobKind,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    Job,
    OutboxEvent,
    SecondaryTaskCancellation,
)
from telegram_agent.core.content_processing.services.async_download_request_service import (
    AsyncDownloadRequestService,
)
from telegram_agent.core.content_processing.services.sync_secondary_task_cancellation_service import (
    SyncSecondaryTaskCancellationService,
)


def test_register_cancels_only_current_chat_secondary_tasks(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    source_job_id = _seed_job(content_sync_sessionmaker, status=JobStatus.RUNNING)
    queued_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.QUEUED,
        requested_dub_language="es",
        reply_to_message_id=10,
    )
    running_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.RUNNING,
        requested_subtitle_language="fa",
        reply_to_message_id=11,
    )
    plain_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.QUEUED,
        reply_to_message_id=12,
    )
    other_chat_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.QUEUED,
        requested_dub_language="de",
        reply_to_message_id=13,
        chat_id=999,
    )
    newer_request_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.QUEUED,
        requested_subtitle_language="ja",
        reply_to_message_id=21,
    )
    delivering_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        requested_dub_language="fr",
        reply_to_message_id=14,
        delivery_status=DownloadDeliveryStatus.SENDING,
    )

    result = SyncSecondaryTaskCancellationService(
        uow_factory=content_sync_uow_factory
    ).register(
        telegram_user_id=7,
        chat_id=100,
        cutoff_message_id=20,
        idempotency_key="cancel-all:test:1",
    )

    assert result.matched_active_count == 2
    with content_sync_sessionmaker() as session:
        queued = session.get(Job, queued_id)
        running = session.get(Job, running_id)
        source = session.get(Job, source_job_id)
        plain = session.get(Job, plain_id)
        other_chat = session.get(Job, other_chat_id)
        newer_request = session.get(Job, newer_request_id)
        delivering = session.get(Job, delivering_id)
        queued_request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == queued_id)
        )
        delivering_request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == delivering_id)
        )
        cancellation_event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.job_id == running_id,
                OutboxEvent.event_type
                == OutboxEventType.DOWNLOAD_CANCELLATION_REQUESTED.value,
            )
        )
    assert queued is not None and queued.status == JobStatus.CANCELLED
    assert running is not None and running.status == JobStatus.CANCELLING
    assert source is not None and source.status == JobStatus.RUNNING
    assert plain is not None and plain.status == JobStatus.QUEUED
    assert other_chat is not None and other_chat.status == JobStatus.QUEUED
    assert newer_request is not None and newer_request.status == JobStatus.QUEUED
    assert delivering is not None and delivering.status == JobStatus.COMPLETED
    assert queued_request is not None
    assert queued_request.delivery_status == DownloadDeliveryStatus.CANCELLED
    assert queued_request.cancelled_at is not None
    assert delivering_request is not None
    assert delivering_request.delivery_status == DownloadDeliveryStatus.SENDING
    assert delivering_request.cancelled_by_id is None
    assert cancellation_event is not None


def test_registration_is_idempotent(
    content_sync_uow_factory,
) -> None:
    service = SyncSecondaryTaskCancellationService(
        uow_factory=content_sync_uow_factory
    )
    first = service.register(
        telegram_user_id=7,
        chat_id=100,
        cutoff_message_id=20,
        idempotency_key="cancel-all:test:stable",
    )
    second = service.register(
        telegram_user_id=7,
        chat_id=100,
        cutoff_message_id=20,
        idempotency_key="cancel-all:test:stable",
    )
    assert first.cancellation_id == second.cancellation_id
    assert first.created is True
    assert second.created is False


@pytest.mark.asyncio
async def test_delayed_earlier_handoff_is_created_cancelled(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    content_uow_factory,
) -> None:
    cancellation = SyncSecondaryTaskCancellationService(
        uow_factory=content_sync_uow_factory
    ).register(
        telegram_user_id=7,
        chat_id=100,
        cutoff_message_id=20,
        idempotency_key="cancel-all:test:barrier",
    )
    result = await AsyncDownloadRequestService(
        uow_factory=content_uow_factory,
        app_settings=settings,
    ).create_download_request(
        CreateDownloadRequestCommand(
            chat_id=100,
            telegram_user_id=7,
            group_id=uuid4(),
            agent_message_id=uuid4(),
            media_ingress_message_id=uuid4(),
            media_type="video",
            assistant_text="Preparing subtitles",
            reply_to_message_id=19,
            requested_subtitle_language="fa",
            idempotency_key="handoff-before-cancel",
        )
    )
    assert result.status == JobStatus.CANCELLED
    with content_sync_sessionmaker() as session:
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == result.job_id)
        )
        events = list(
            session.scalars(
                select(OutboxEvent).where(OutboxEvent.job_id == result.job_id)
            )
        )
    assert request is not None
    assert request.cancelled_by_id == cancellation.cancellation_id
    assert request.cancelled_at is not None
    assert events == []


def _seed_job(
    sessionmaker_: sessionmaker[Session], *, status: JobStatus
):
    job = Job(
        kind=JobKind.TELEGRAM_ATTACHMENT,
        status=status,
        idempotency_key=f"source:{uuid4()}",
        callback_required=False,
    )
    with sessionmaker_() as session:
        session.add(job)
        session.commit()
    return job.id


def _seed_request(
    sessionmaker_: sessionmaker[Session],
    *,
    status: JobStatus,
    reply_to_message_id: int,
    requested_dub_language: str | None = None,
    requested_subtitle_language: str | None = None,
    chat_id: int = 100,
    delivery_status: DownloadDeliveryStatus = DownloadDeliveryStatus.PENDING,
):
    job = Job(
        kind=JobKind.DOWNLOAD_PREPARATION,
        status=status,
        idempotency_key=f"request:{uuid4()}",
        callback_required=False,
    )
    request = DownloadRequest(
        job=job,
        chat_id=chat_id,
        telegram_user_id=7,
        group_id=uuid4(),
        agent_message_id=uuid4(),
        media_ingress_message_id=uuid4(),
        media_type="video",
        requested_dub_language=requested_dub_language,
        requested_subtitle_language=requested_subtitle_language,
        assistant_text="prepare",
        reply_to_message_id=reply_to_message_id,
        delivery_status=delivery_status,
    )
    with sessionmaker_() as session:
        session.add(request)
        session.commit()
    return job.id
