from telegram_agent.core.gpu_execution.celery.celery_app import celery_app
from telegram_agent.core.gpu_execution.services.outbox_dispatcher import SyncGpuOutboxDispatcher


@celery_app.task(name="gpu.outbox.dispatch")
def dispatch_gpu_outbox_task() -> dict[str, int]:
    return SyncGpuOutboxDispatcher.from_settings(celery_app).dispatch_once()
