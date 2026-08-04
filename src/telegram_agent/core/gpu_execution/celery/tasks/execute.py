from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.gpu_execution.celery.celery_app import celery_app
from telegram_agent.core.gpu_execution.services.execution_service import SyncGpuExecutionService


logger = get_task_logger(__name__)


@celery_app.task(name="gpu.execute", bind=True, max_retries=None)
def execute_gpu_job_task(self, job_id: str) -> None:
    try:
        parsed_job_id = UUID(job_id)
    except (TypeError, ValueError):
        logger.warning("Ignoring GPU execution task with invalid job id", extra={"job_id": job_id})
        return
    result = SyncGpuExecutionService.from_settings().execute(parsed_job_id)
    if result.resource_busy:
        raise self.retry(countdown=5, max_retries=None)
