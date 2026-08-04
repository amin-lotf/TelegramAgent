from celery import Celery
from kombu import Exchange, Queue

from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.gpu_execution.common.settings import settings


def create_celery_app() -> Celery:
    setup_logging(settings.LOG_LEVEL)
    app = Celery(
        "gpu_execution",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "telegram_agent.core.gpu_execution.celery.tasks.execute",
            "telegram_agent.core.gpu_execution.celery.tasks.outbox",
            "telegram_agent.core.gpu_execution.celery.tasks.recovery",
        ],
    )
    exchange = Exchange("gpu_execution", type="direct")
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        timezone="UTC",
        enable_utc=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_exchange="gpu_execution",
        task_default_exchange_type="direct",
        task_default_queue="gpu_execution_control",
        task_default_routing_key="gpu.control",
        task_queues=(
            Queue("gpu_execution", exchange, routing_key="gpu.execute"),
            Queue("gpu_execution_control", exchange, routing_key="gpu.control"),
        ),
        task_routes={
            "gpu.execute": {"queue": "gpu_execution", "routing_key": "gpu.execute"},
            "gpu.outbox.dispatch": {
                "queue": "gpu_execution_control",
                "routing_key": "gpu.control",
            },
            "gpu.recover": {
                "queue": "gpu_execution_control",
                "routing_key": "gpu.control",
            },
        },
        beat_schedule={
            "dispatch-gpu-outbox": {
                "task": "gpu.outbox.dispatch",
                "schedule": settings.gpu_outbox_poll_interval_seconds,
            },
            "recover-stale-gpu-jobs": {
                "task": "gpu.recover",
                "schedule": settings.gpu_recovery_poll_interval_seconds,
            },
        },
    )
    return app


celery_app = create_celery_app()
