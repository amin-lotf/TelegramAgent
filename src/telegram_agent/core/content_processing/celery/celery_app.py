from celery import Celery
from kombu import Exchange, Queue

from telegram_agent.core.common.logging import setup_logging
from telegram_agent.core.content_processing.common.settings import settings


def create_celery_app() -> Celery:
    setup_logging(settings.LOG_LEVEL)
    celery_app = Celery(
        "content_processor",
        broker=settings.redis_url,
        backend=settings.redis_url,
        include=[
            "telegram_agent.core.content_processing.celery.tasks.media_download",
            "telegram_agent.core.content_processing.celery.tasks.transcription",
            "telegram_agent.core.content_processing.celery.tasks.emotion_extraction",
            "telegram_agent.core.content_processing.celery.tasks.chunking",
            "telegram_agent.core.content_processing.celery.tasks.embedding",
            "telegram_agent.core.content_processing.celery.tasks.outbox_dispatch",
            "telegram_agent.core.content_processing.celery.tasks.telegram_ingress_callback",
            "telegram_agent.core.content_processing.celery.tasks.job_expectation_sweep",
            "telegram_agent.core.content_processing.celery.tasks.download_preparation",
            "telegram_agent.core.content_processing.celery.tasks.download_delivery",
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
            Queue(
                "media_transcription",
                Exchange("content_processing", type="direct"),
                routing_key="media.transcribe",
            ),
            Queue(
                "media_emotion_extraction",
                Exchange("content_processing", type="direct"),
                routing_key="media.extract_emotions",
            ),
            Queue(
                "media_chunking",
                Exchange("content_processing", type="direct"),
                routing_key="media.chunk",
            ),
            Queue(
                "media_embedding",
                Exchange("content_processing", type="direct"),
                routing_key="media.embed",
            ),
            Queue(
                "outbox_dispatch",
                Exchange("content_processing", type="direct"),
                routing_key="outbox.dispatch",
            ),
            Queue(
                "telegram_ingress_callback",
                Exchange("content_processing", type="direct"),
                routing_key="telegram_ingress.processing_result",
            ),
            Queue(
                "download_preparation",
                Exchange("content_processing", type="direct"),
                routing_key="download.prepare",
            ),
            Queue(
                "download_delivery",
                Exchange("content_processing", type="direct"),
                routing_key="download.deliver",
            ),
        ),

        task_routes={
            "outbox.dispatch": {
                "queue": "outbox_dispatch",
                "routing_key": "outbox.dispatch",
            },
            "job_expectations.sweep": {
                "queue": "outbox_dispatch",
                "routing_key": "outbox.dispatch",
            },
            "telegram.download": {
                "queue": "telegram_download",
                "routing_key": "telegram.download",
            },
            "media.transcribe": {
                "queue": "media_transcription",
                "routing_key": "media.transcribe",
            },
            "media.extract_emotions": {
                "queue": "media_emotion_extraction",
                "routing_key": "media.extract_emotions",
            },
            "media.chunk": {
                "queue": "media_chunking",
                "routing_key": "media.chunk",
            },
            "media.embed": {
                "queue": "media_embedding",
                "routing_key": "media.embed",
            },
            "telegram_ingress.processing_result": {
                "queue": "telegram_ingress_callback",
                "routing_key": "telegram_ingress.processing_result",
            },
            "download.prepare": {
                "queue": "download_preparation",
                "routing_key": "download.prepare",
            },
            "download.deliver": {
                "queue": "download_delivery",
                "routing_key": "download.deliver",
            },
        },

        beat_schedule={
            "dispatch-content-processing-outbox": {
                "task": "outbox.dispatch",
                "schedule": settings.outbox_dispatch_poll_interval_seconds,
            },
            "sweep-job-completion-expectations": {
                "task": "job_expectations.sweep",
                "schedule": settings.job_expectation_sweep_interval_seconds,
            },
        },
    )

    return celery_app


celery_app = create_celery_app()
