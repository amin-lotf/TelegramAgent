from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.content_processing.common.commands import CreateTelegramJobCommand
from telegram_agent.core.content_processing.common.types import JobStatus, OutboxEventStatus, OutboxEventType
from telegram_agent.core.content_processing.db.models.content_processing import Job, MediaAsset, OutboxEvent, TelegramSource
from telegram_agent.core.content_processing.db.uow.async_content_processing import (
    AsyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.services.async_telegram_job_service import AsyncTelegramJobService

pytestmark = pytest.mark.asyncio


async def test_create_job_persists_job_related_records_and_outbox_atomically(
    content_uow_factory,
    content_sessionmaker,
) -> None:
    service = AsyncTelegramJobService(uow_factory=content_uow_factory)
    command = _create_command(idempotency_key="telegram-job-001")

    result = await service.create_job(command)

    assert result.created is True
    assert result.status == JobStatus.QUEUED

    async with content_sessionmaker() as session:
        job = await session.get(Job, result.job_id)
        source = (
            await session.execute(select(TelegramSource).where(TelegramSource.job_id == result.job_id))
        ).scalar_one_or_none()
        asset = (
            await session.execute(select(MediaAsset).where(MediaAsset.job_id == result.job_id))
        ).scalar_one_or_none()
        event = (
            await session.execute(select(OutboxEvent).where(OutboxEvent.job_id == result.job_id))
        ).scalar_one_or_none()

    assert job is not None
    assert job.status == JobStatus.QUEUED
    assert source is not None
    assert source.telegram_file_id == command.telegram_file_id
    assert asset is not None
    assert asset.local_path is None
    assert asset.media_type == TelegramAttachmentType.VOICE.value
    assert event is not None
    assert event.event_type == OutboxEventType.CONTENT_PROCESSING_JOB_READY
    assert event.job_id == result.job_id
    assert event.idempotency_key == (
        f"{OutboxEventType.CONTENT_PROCESSING_JOB_READY.value}:{result.job_id}"
    )
    assert event.payload == {}
    assert event.status == OutboxEventStatus.PENDING


async def test_create_job_rolls_back_job_and_outbox_when_late_write_fails(
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

    service = AsyncTelegramJobService(uow_factory=failing_uow_factory)

    with pytest.raises(RuntimeError, match="outbox write failed"):
        await service.create_job(_create_command(idempotency_key="rollback-job"))

    async with content_sessionmaker() as session:
        job_count = await session.scalar(select(func.count()).select_from(Job))
        event_count = await session.scalar(select(func.count()).select_from(OutboxEvent))
        source_count = await session.scalar(select(func.count()).select_from(TelegramSource))
        asset_count = await session.scalar(select(func.count()).select_from(MediaAsset))

    assert job_count == 0
    assert event_count == 0
    assert source_count == 0
    assert asset_count == 0


async def test_duplicate_idempotency_key_returns_existing_job_without_duplicate_outbox(
    content_uow_factory,
    content_sessionmaker,
) -> None:
    service = AsyncTelegramJobService(uow_factory=content_uow_factory)
    command = _create_command(idempotency_key="duplicate-job")

    first = await service.create_job(command)
    second = await service.create_job(command)

    assert first.created is True
    assert second.created is False
    assert second.job_id == first.job_id

    async with content_sessionmaker() as session:
        event_count = await session.scalar(
            select(func.count()).select_from(OutboxEvent).where(OutboxEvent.job_id == first.job_id)
        )

    assert event_count == 1


def _create_command(*, idempotency_key: str) -> CreateTelegramJobCommand:
    return CreateTelegramJobCommand(
        ingress_message_id=uuid4(),
        ingress_attachment_id=uuid4(),
        telegram_user_id=555000111,
        telegram_file_id="telegram-file-001",
        telegram_file_unique_id="telegram-unique-001",
        attachment_type=TelegramAttachmentType.VOICE,
        callback_required=True,
        idempotency_key=idempotency_key,
    )
