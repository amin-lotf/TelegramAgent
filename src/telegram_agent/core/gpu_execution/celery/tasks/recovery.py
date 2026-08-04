from telegram_agent.core.gpu_execution.celery.celery_app import celery_app
from telegram_agent.core.gpu_execution.services.recovery_service import SyncGpuRecoveryService


@celery_app.task(name="gpu.recover")
def recover_gpu_jobs_task() -> dict[str, int]:
    return SyncGpuRecoveryService.from_settings().recover_once()
