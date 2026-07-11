from contextlib import AbstractAsyncContextManager
from typing import Callable

from sqlalchemy.exc import IntegrityError

from telegram_agent.core.common.exceptions import JobCreationError
from telegram_agent.core.content_processing.common.commands import CreateTelegramJobCommand
from telegram_agent.core.content_processing.common.const import CONTENT_PROCESSING_JOB_AGGREGATE_TYPE
from telegram_agent.core.content_processing.common.results import CreateTelegramJobResult
from telegram_agent.core.content_processing.common.types import JobKind, JobStatus, OutboxEventType
from telegram_agent.core.content_processing.db.models.content_processing import Job, MediaAsset, OutboxEvent, TelegramSource
from telegram_agent.core.content_processing.db.uow.async_content_processing import \
    AsyncSqlAlchemyContentProcessingUnitOfWork


class AsyncTelegramJobService:
    def __init__(
            self,
            uow_factory: Callable[
                [],
                AbstractAsyncContextManager[AsyncSqlAlchemyContentProcessingUnitOfWork],
            ],
    ):
        self._uow_factory = uow_factory

    async def create_job(
            self,
            command: CreateTelegramJobCommand,
    ) -> CreateTelegramJobResult:
        try:
            async with self._uow_factory() as uow:
                existing_job = await uow.jobs.get_by_idempotency_key(
                    command.idempotency_key,
                )

                if existing_job is not None:
                    return CreateTelegramJobResult(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        created=False,
                    )

                job = Job(
                    kind=JobKind.TELEGRAM_ATTACHMENT,
                    status=JobStatus.QUEUED,
                    idempotency_key=command.idempotency_key,
                    callback_required=command.callback_required,
                )

                await uow.jobs.add(job)

                telegram_source = TelegramSource(
                    job_id=job.id,
                    ingress_message_id=command.ingress_message_id,
                    ingress_attachment_id=command.ingress_attachment_id,
                    telegram_user_id=command.telegram_user_id,
                    telegram_file_id=command.telegram_file_id,
                    telegram_file_unique_id=command.telegram_file_unique_id,
                    attachment_type=command.attachment_type,
                )

                await uow.telegram_sources.add(telegram_source)

                media_asset = MediaAsset(
                    job_id=job.id,
                    local_path=None,
                    media_type=command.attachment_type.value,
                    mime_type=None,
                    duration_ms=None,
                    size_bytes=None,
                )

                await uow.media_assets.add(media_asset)

                outbox_event = OutboxEvent(
                    event_type=OutboxEventType.CONTENT_PROCESSING_JOB_READY,
                    aggregate_type=CONTENT_PROCESSING_JOB_AGGREGATE_TYPE,
                    aggregate_id=job.id,
                    payload={"job_id": str(job.id)},
                )

                await uow.outbox_events.add(outbox_event)

                return CreateTelegramJobResult(
                    job_id=job.id,
                    status=job.status,
                    created=True,
                )


        except IntegrityError as exc:
            # The first UoW has exited and rolled back by this point.
            async with self._uow_factory() as uow:
                existing_job = await uow.jobs.get_by_idempotency_key(
                    command.idempotency_key,
                )
                if existing_job is not None:
                    return CreateTelegramJobResult(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        created=False,
                    )
            # It was not the expected idempotency collision.
            raise JobCreationError(
                "Failed to persist content-processing job"
            ) from exc
