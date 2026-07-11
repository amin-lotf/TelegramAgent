from __future__ import annotations

from celery.utils.log import get_task_logger

from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.services.outbox_dispatcher import OutboxDispatcher

logger = get_task_logger(__name__)


@celery_app.task(
    name="outbox.dispatch",
)
def dispatch_outbox_task() -> dict[str, int]:
    result = OutboxDispatcher.from_settings().dispatch_once()
    logger.info(
        "Completed outbox dispatch poll",
        extra={
            "claimed": result.claimed,
            "published": result.published,
            "retryable_failures": result.retryable_failures,
            "permanent_failures": result.permanent_failures,
        },
    )
    return {
        "claimed": result.claimed,
        "published": result.published,
        "retryable_failures": result.retryable_failures,
        "permanent_failures": result.permanent_failures,
    }
