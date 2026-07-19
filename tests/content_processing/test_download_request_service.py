from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from telegram_agent.core.content_processing.common.commands import (
    CreateDownloadRequestCommand,
)
from telegram_agent.core.content_processing.common.types import (
    JobCompletionExpectationStatus,
    JobKind,
    JobStatus,
    OutboxEventStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    Job,
    JobCompletionExpectation,
    OutboxEvent,
)
from telegram_agent.core.content_processing.db.uow.async_content_processing import (
    AsyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.services.async_download_request_service import (
    AsyncDownloadRequestService,
)

pytestmark = pytest.mark.asyncio


async def test_create_download_request_persists_job_request_and_outbox(
    content_uow_factory,
    content_sessionmaker,
) -> None:
    service = AsyncDownloadRequestService(uow_factory=content_uow_factory)
    command = _create_command(idempotency_key="download-req-001")

    result = await service.create_download_request(command)

    assert result.created is True
    assert result.status == JobStatus.QUEUED
    assert result.media_type == "video"

    async with content_sessionmaker() as session:
        job = await session.get(Job, result.job_id)
        request = (
            await session.execute(
                select(DownloadRequest).where(DownloadRequest.job_id == result.job_id)
            )
        ).scalar_one_or_none()
        event = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.job_id == result.job_id)
            )
        ).scalar_one_or_none()
        expectation = (
            await session.execute(
                select(JobCompletionExpectation).where(
                    JobCompletionExpectation.job_id == result.job_id
                )
            )
        ).scalar_one_or_none()

    assert job is not None
    assert job.kind == JobKind.DOWNLOAD_PREPARATION
    assert job.callback_required is False
    assert request is not None
    assert request.chat_id == command.chat_id
    assert request.media_ingress_message_id == command.media_ingress_message_id
    assert request.requested_subtitle_language == "en"
    assert request.final_path is None
    assert event is not None
    assert event.event_type == OutboxEventType.DOWNLOAD_PREPARATION_READY
    assert event.idempotency_key == (
        f"{OutboxEventType.DOWNLOAD_PREPARATION_READY.value}:{result.job_id}"
    )
    assert event.status == OutboxEventStatus.PENDING
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.OPEN


async def test_duplicate_idempotency_key_returns_existing_without_duplicate_rows(
    content_uow_factory,
    content_sessionmaker,
) -> None:
    service = AsyncDownloadRequestService(uow_factory=content_uow_factory)
    command = _create_command(idempotency_key="download-dup")

    first = await service.create_download_request(command)
    second = await service.create_download_request(command)

    assert first.created is True
    assert second.created is False
    assert second.job_id == first.job_id

    async with content_sessionmaker() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        request_count = await session.scalar(
            select(func.count()).select_from(DownloadRequest)
        )
        event_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        )

    assert job_count == 1
    assert request_count == 1
    assert event_count == 1


async def test_create_download_request_rolls_back_when_outbox_write_fails(
    content_sessionmaker,
) -> None:
    class FailingOutboxRepository:
        def __init__(self, wrapped) -> None:
            self._wrapped = wrapped

        async def add(self, event: OutboxEvent) -> OutboxEvent:
            await self._wrapped.add(event)
            raise RuntimeError("outbox write failed")

    @asynccontextmanager
    async def failing_uow_factory():
        async with content_sessionmaker() as session:
            async with AsyncSqlAlchemyContentProcessingUnitOfWork(session) as uow:
                uow.outbox_events = FailingOutboxRepository(uow.outbox_events)
                yield uow

    service = AsyncDownloadRequestService(uow_factory=failing_uow_factory)

    with pytest.raises(RuntimeError, match="outbox write failed"):
        await service.create_download_request(
            _create_command(idempotency_key="download-rollback")
        )

    async with content_sessionmaker() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        request_count = await session.scalar(
            select(func.count()).select_from(DownloadRequest)
        )
        event_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent)
        )

    assert job_count == 0
    assert request_count == 0
    assert event_count == 0


def _create_command(*, idempotency_key: str) -> CreateDownloadRequestCommand:
    return CreateDownloadRequestCommand(
        chat_id=12345,
        telegram_user_id=555000111,
        group_id=uuid4(),
        agent_message_id=uuid4(),
        media_ingress_message_id=uuid4(),
        media_type="video",
        assistant_text="Preparing your video download.",
        requested_subtitle_language="en",
        requested_dub_language=None,
        idempotency_key=idempotency_key,
    )
