from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.sync_transcription_service import (
    SyncTranscriptionService,
)

logger = get_task_logger(__name__)


@celery_app.task(name="media.transcribe", bind=True)
def transcribe_media_task(self, job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except (TypeError, ValueError):
        logger.warning("Ignoring transcription task with invalid job id", extra={"job_id": job_id})
        return

    result = SyncTranscriptionService.from_settings().execute(job_id=parsed_job_id, retry_count=self.request.retries)
    if result.retryable:
        raise self.retry(
            countdown=settings.media_task_retry_base_seconds * (2 ** self.request.retries),
            max_retries=settings.media_task_max_retries,
        )
