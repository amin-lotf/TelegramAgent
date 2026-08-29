from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from typing import Callable

from sqlalchemy.exc import IntegrityError

from telegram_agent.core.common.exceptions import JobCreationError
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.common.commands import (
    CreateDownloadRequestCommand,
)
from telegram_agent.core.content_processing.common.results import (
    CreateDownloadRequestResult,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    JobCompletionExpectationKind,
    JobCompletionExpectationStatus,
    JobKind,
    JobStatus,
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


class AsyncDownloadRequestService:
    def __init__(
        self,
        uow_factory: Callable[
            [],
            AbstractAsyncContextManager[AsyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        app_settings: Settings | None = None,
    ):
        self._uow_factory = uow_factory
        self._settings = app_settings if app_settings is not None else settings

    async def create_download_request(
        self,
        command: CreateDownloadRequestCommand,
    ) -> CreateDownloadRequestResult:
        try:
            async with self._uow_factory() as uow:
                existing_job = await uow.jobs.get_by_idempotency_key(
                    command.idempotency_key,
                )
                if existing_job is not None:
                    return CreateDownloadRequestResult(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        created=False,
                        media_type=command.media_type,
                    )

                is_secondary = bool(
                    command.requested_subtitle_language
                    or command.requested_dub_language
                )
                if is_secondary and command.reply_to_message_id is None:
                    raise JobCreationError(
                        "Dub/subtitle requests require reply_to_message_id"
                    )
                covering_cancellation = None
                if is_secondary and command.reply_to_message_id is not None:
                    await uow.secondary_task_cancellations.lock_scope(
                        telegram_user_id=command.telegram_user_id,
                        chat_id=command.chat_id,
                    )
                    covering_cancellation = (
                        await uow.secondary_task_cancellations.find_covering(
                            telegram_user_id=command.telegram_user_id,
                            chat_id=command.chat_id,
                            request_message_id=command.reply_to_message_id,
                        )
                    )

                job = Job(
                    kind=JobKind.DOWNLOAD_PREPARATION,
                    status=(
                        JobStatus.CANCELLED
                        if covering_cancellation is not None
                        else JobStatus.QUEUED
                    ),
                    idempotency_key=command.idempotency_key,
                    callback_required=False,
                    error_message=(
                        "Cancelled by an earlier /cancel_all command"
                        if covering_cancellation is not None
                        else None
                    ),
                )
                await uow.jobs.add(job)

                download_request = DownloadRequest(
                    job_id=job.id,
                    chat_id=command.chat_id,
                    telegram_user_id=command.telegram_user_id,
                    group_id=command.group_id,
                    agent_message_id=command.agent_message_id,
                    media_ingress_message_id=command.media_ingress_message_id,
                    media_type=command.media_type,
                    requested_subtitle_language=command.requested_subtitle_language,
                    requested_dub_language=command.requested_dub_language,
                    requested_language=command.requested_language,
                    requested_format=command.requested_format,
                    assistant_text=command.assistant_text,
                    reply_to_message_id=command.reply_to_message_id,
                    final_path=None,
                    cancelled_by_id=(
                        covering_cancellation.id
                        if covering_cancellation is not None
                        else None
                    ),
                    cancellation_requested_at=(
                        utcnow() if covering_cancellation is not None else None
                    ),
                    cancelled_at=(
                        utcnow() if covering_cancellation is not None else None
                    ),
                    delivery_status=(
                        DownloadDeliveryStatus.CANCELLED
                        if covering_cancellation is not None
                        else DownloadDeliveryStatus.PENDING
                    ),
                )
                await uow.download_requests.add(download_request)

                if covering_cancellation is not None:
                    return CreateDownloadRequestResult(
                        job_id=job.id,
                        status=job.status,
                        created=True,
                        media_type=command.media_type,
                    )

                event_type = OutboxEventType.DOWNLOAD_PREPARATION_READY
                await uow.outbox_events.add(
                    OutboxEvent(
                        event_type=event_type,
                        job_id=job.id,
                        idempotency_key=f"{event_type.value}:{job.id}",
                        payload={},
                    )
                )

                # Download prep includes ffmpeg mux; use a longer SLA than the
                # default attachment expectation (often 60s) so the sweeper does
                # not time the job out mid-mux.
                if command.requested_dub_language:
                    expectation_seconds = max(
                        self._settings.job_expectation_default_seconds,
                        int(self._settings.cosyvoice_request_timeout_seconds)
                        + int(self._settings.sam_audio_request_timeout_seconds)
                        + 1800,
                    )
                else:
                    expectation_seconds = max(
                        self._settings.job_expectation_default_seconds,
                        600,
                    )
                await uow.job_expectations.add(
                    JobCompletionExpectation(
                        job_id=job.id,
                        kind=JobCompletionExpectationKind.JOB_COMPLETION,
                        status=JobCompletionExpectationStatus.OPEN,
                        due_at=utcnow() + timedelta(seconds=expectation_seconds),
                    )
                )

                return CreateDownloadRequestResult(
                    job_id=job.id,
                    status=job.status,
                    created=True,
                    media_type=command.media_type,
                )

        except IntegrityError as exc:
            async with self._uow_factory() as uow:
                existing_job = await uow.jobs.get_by_idempotency_key(
                    command.idempotency_key,
                )
                if existing_job is not None:
                    return CreateDownloadRequestResult(
                        job_id=existing_job.id,
                        status=existing_job.status,
                        created=False,
                        media_type=command.media_type,
                    )
            raise JobCreationError(
                "Failed to persist download preparation job"
            ) from exc
