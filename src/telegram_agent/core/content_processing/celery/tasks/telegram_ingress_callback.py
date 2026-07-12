from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger
from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    TelegramIngressBadResponseError,
    TelegramIngressUnavailableError,
)
from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.sync_telegram_ingress_callback import (
    SyncTelegramIngressCallbackService,
)

logger = get_task_logger(__name__)


@celery_app.task(name="telegram_ingress.processing_result", bind=True)
def notify_telegram_ingress_task(self, job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring ingress callback task with invalid job id",
            extra={"job_id": job_id},
        )
        return

    try:
        SyncTelegramIngressCallbackService.from_settings().execute(parsed_job_id)
    except (TelegramIngressUnavailableError, SQLAlchemyError) as exc:
        raise self.retry(
            exc=exc,
            countdown=(
                settings.callback_task_retry_base_seconds
                * (2 ** self.request.retries)
            ),
            max_retries=settings.callback_task_max_retries,
        )
    except (TelegramIngressBadResponseError, PermanentContentProcessingError) as exc:
        logger.error(
            "Telegram ingress callback permanently failed",
            extra={"job_id": job_id, "error": str(exc)},
        )
