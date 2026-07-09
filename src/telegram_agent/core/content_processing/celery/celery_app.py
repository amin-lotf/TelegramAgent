from celery import Celery
from kombu import Exchange, Queue

from telegram_agent.core.content_processing.common.settings import settings


def create_celery_app() -> Celery:
    celery_app = Celery(
        "content_processor",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[

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

        task_default_exchange="content_processing",
        task_default_exchange_type="direct",
        task_default_queue="default",
        task_default_routing_key="default",

        task_queues=(
            Queue(
                "telegram_download",
                Exchange("content_processing", type="direct"),
                routing_key="telegram.download",
            ),
        ),

        task_routes={
            "telegram.download": {
                "queue": "telegram_download",
                "routing_key": "telegram.download",
            },
        },
    )

    return celery_app


celery_app = create_celery_app()