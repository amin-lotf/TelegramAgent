from celery import Celery
from kombu import Exchange, Queue

from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.common.logging import setup_logging


def create_celery_app() -> Celery:
    setup_logging(settings.LOG_LEVEL)
    celery_app = Celery(
        "agent_runtime",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "telegram_agent.core.agent_runtime.celery.tasks.outbox_dispatch",
            "telegram_agent.core.agent_runtime.celery.tasks.coordinate_conversation",
            "telegram_agent.core.agent_runtime.celery.tasks.classify_intent",
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
        task_default_exchange="agent_runtime",
        task_default_exchange_type="direct",
        task_default_queue="agent_runtime_default",
        task_default_routing_key="agent_runtime.default",
        task_queues=(
            Queue(
                "agent_runtime_outbox",
                Exchange("agent_runtime", type="direct"),
                routing_key="agent_runtime.outbox.dispatch",
            ),
            Queue(
                "agent_runtime_coordination",
                Exchange("agent_runtime", type="direct"),
                routing_key="agent_runtime.coordinate_conversation",
            ),
            Queue(
                "agent_runtime_classification",
                Exchange("agent_runtime", type="direct"),
                routing_key="agent_runtime.classify_intent",
            ),
        ),
        task_routes={
            "coordination.outbox.dispatch": {
                "queue": "agent_runtime_outbox",
                "routing_key": "agent_runtime.outbox.dispatch",
            },
            "agent_runtime.coordinate_conversation": {
                "queue": "agent_runtime_coordination",
                "routing_key": "agent_runtime.coordinate_conversation",
            },
            "agent_runtime.classify_intent": {
                "queue": "agent_runtime_classification",
                "routing_key": "agent_runtime.classify_intent",
            },
        },
        beat_schedule={
            "dispatch-agent-runtime-coordination-outbox": {
                "task": "coordination.outbox.dispatch",
                "schedule": settings.outbox_dispatch_poll_interval_seconds,
            },
        },
    )
    return celery_app


celery_app = create_celery_app()
