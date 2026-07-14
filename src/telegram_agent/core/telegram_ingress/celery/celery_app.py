from celery import Celery
from kombu import Exchange, Queue

from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.telegram_ingress.common.settings import settings


def create_celery_app() -> Celery:
    setup_logging(settings.LOG_LEVEL)
    celery_app = Celery(
        "telegram_ingress",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "telegram_agent.core.telegram_ingress.celery.tasks.outbox_publish",
        ],
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_exchange="telegram_ingress",
        task_default_exchange_type="direct",
        task_default_queue="telegram_ingress_default",
        task_default_routing_key="telegram_ingress.default",
        task_queues=(
            Queue(
                "telegram_ingress_outbox",
                Exchange("telegram_ingress", type="direct"),
                routing_key="telegram_ingress.outbox.publish",
            ),
        ),
        task_routes={
            "telegram_ingress.outbox.publish": {
                "queue": "telegram_ingress_outbox",
                "routing_key": "telegram_ingress.outbox.publish",
            },
        },
        beat_schedule={
            "publish-telegram-ingress-outbox": {
                "task": "telegram_ingress.outbox.publish",
                "schedule": settings.outbox_dispatch_poll_interval_seconds,
            },
        },
    )
    return celery_app


celery_app = create_celery_app()
