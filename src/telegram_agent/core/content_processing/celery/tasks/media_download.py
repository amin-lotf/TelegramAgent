from __future__ import annotations
from celery.utils.log import get_task_logger
from telegram_agent.core.content_processing.celery.celery_app import celery_app
logger = get_task_logger(__name__)



@celery_app.task(
    name="telegram.download",
    bind=True,
)
def download_telegram_source_task(self, job_id: str) -> None:
    pass
