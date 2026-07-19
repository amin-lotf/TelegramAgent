from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.sync_download_preparation_service import (
    SyncDownloadPreparationService,
)

logger = get_task_logger(__name__)


# Waiting for the original attachment job (download + transcription) can take
# longer than a normal media stage. Prefer many short waits over failing early.
_DOWNLOAD_PREPARE_MAX_RETRIES = 36
_DOWNLOAD_PREPARE_WAIT_COUNTDOWN_SECONDS = 10


@celery_app.task(name="download.prepare", bind=True)
def prepare_download_task(self, job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring download preparation task with invalid job id",
            extra={"job_id": job_id},
        )
        return

    result = SyncDownloadPreparationService.from_settings().execute(
        job_id=parsed_job_id,
        retry_count=self.request.retries,
    )
    if result.retryable:
        waiting_for_source = "waiting" in (result.error_message or "").lower()
        if waiting_for_source:
            countdown = _DOWNLOAD_PREPARE_WAIT_COUNTDOWN_SECONDS
            max_retries = _DOWNLOAD_PREPARE_MAX_RETRIES
        else:
            countdown = settings.media_task_retry_base_seconds * (
                2 ** self.request.retries
            )
            max_retries = max(
                settings.media_task_max_retries,
                _DOWNLOAD_PREPARE_MAX_RETRIES,
            )
        logger.info(
            "Retrying download preparation",
            extra={
                "job_id": job_id,
                "retry_count": self.request.retries,
                "countdown": countdown,
                "error_message": result.error_message,
            },
        )
        raise self.retry(
            countdown=countdown,
            max_retries=max_retries,
        )
