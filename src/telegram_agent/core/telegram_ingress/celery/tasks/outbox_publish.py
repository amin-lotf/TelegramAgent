from celery.utils.log import get_task_logger

from telegram_agent.core.telegram_ingress.celery.celery_app import celery_app
from telegram_agent.core.telegram_ingress.services.outbox_publisher import OutboxPublisher

logger = get_task_logger(__name__)


@celery_app.task(name="telegram_ingress.outbox.publish")
def publish_outbox_task() -> dict[str, int]:
    result = OutboxPublisher.from_settings().dispatch_once()
    logger.info(
        "Completed Telegram-ingress outbox publication poll",
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
