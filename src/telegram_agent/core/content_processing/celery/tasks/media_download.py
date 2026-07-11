from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.db.uow.sync_uow_factory import sync_content_processing_uow_factory

logger = get_task_logger(__name__)


@celery_app.task(
    name="telegram.download",
    bind=True,
)
def download_telegram_source_task(self, job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except ValueError:
        logger.warning("Ignoring media download task with invalid job id", extra={"job_id": job_id})
        return

    with sync_content_processing_uow_factory() as uow:
        claimed_job = uow.jobs.claim_for_download(parsed_job_id)

    if claimed_job is None:
        logger.info(
            "Media download job is not claimable; skipping duplicate or stale task",
            extra={"job_id": job_id},
        )
        return

    logger.info(
        "Claimed media download job",
        extra={"job_id": job_id, "task_id": getattr(self.request, "id", None)},
    )
    logger.warning(
        "Media download implementation is not present yet; leaving claimed job in running state",
        extra={"job_id": job_id},
    )
