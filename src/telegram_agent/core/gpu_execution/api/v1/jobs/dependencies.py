from telegram_agent.core.gpu_execution.services.job_service import SyncGpuJobService


def get_gpu_job_service() -> SyncGpuJobService:
    return SyncGpuJobService.from_settings()
