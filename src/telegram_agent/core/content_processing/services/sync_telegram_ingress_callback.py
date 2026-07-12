from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable
from uuid import UUID

from telegram_agent.core.common.exceptions import PermanentContentProcessingError
from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.content_processing.clients.telegram_ingress_client import (
    TelegramIngressClient,
)
from telegram_agent.core.content_processing.common.commands import (
    NotifyAttachmentProcessingResultCommand,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import JobStatus
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
import logging

logger = logging.getLogger(__name__)

_MESSAGE_ATTACHMENT_TYPES = frozenset(
    {
        TelegramAttachmentType.VOICE,
        TelegramAttachmentType.VIDEO_NOTE,
    }
)


class SyncTelegramIngressCallbackService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        client: TelegramIngressClient,
    ) -> None:
        self._uow_factory = uow_factory
        self._client = client

    @classmethod
    def from_settings(cls) -> "SyncTelegramIngressCallbackService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            client=TelegramIngressClient(settings),
        )

    def execute(self, job_id: UUID) -> None:
        command = self._resolve_command(job_id)

        if command is not None:
            self._client.notify_processing_result(command)

    def _resolve_command(
        self,
        job_id: UUID,
    ) -> NotifyAttachmentProcessingResultCommand | None:
        with self._uow_factory() as uow:
            job = uow.jobs.get_by_id(job_id)
            if job is None or not job.callback_required:
                return None
            if job.status not in (JobStatus.COMPLETED, JobStatus.FAILED):
                raise PermanentContentProcessingError(
                    "Ingress callback requested for a non-terminal job"
                )

            sources = uow.telegram_sources.list_by_job_id(job_id)
            if len(sources) != 1:
                raise PermanentContentProcessingError(
                    "Ingress callback requires exactly one Telegram source"
                )
            source = sources[0]

            transcribed_text: str | None = None
            if (
                job.status == JobStatus.COMPLETED
                and source.attachment_type in _MESSAGE_ATTACHMENT_TYPES
            ):
                transcript = uow.transcripts.get_by_job_id(job_id)
                if transcript is None:
                    raise PermanentContentProcessingError(
                        "Completed voice or video-note job has no transcript"
                    )
                transcribed_text = transcript.text

            return NotifyAttachmentProcessingResultCommand(
                ingress_message_id=source.ingress_message_id,
                ingress_attachment_id=source.ingress_attachment_id,
                status=(
                    AttachmentProcessingResultStatus.COMPLETED
                    if job.status == JobStatus.COMPLETED
                    else AttachmentProcessingResultStatus.FAILED
                ),
                transcribed_text=transcribed_text,
            )
