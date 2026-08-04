from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable

from telegram_agent.core.gpu_execution.common.settings import Settings, settings
from telegram_agent.core.gpu_execution.common.types import GpuJobStatus
from telegram_agent.core.gpu_execution.db.models.gpu_execution import GpuOutboxEvent
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import SyncSqlAlchemyGpuExecutionUnitOfWork
from telegram_agent.core.gpu_execution.db.uow.sync_uow_factory import sync_gpu_execution_uow_factory


class SyncGpuRecoveryService:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyGpuExecutionUnitOfWork]],
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings

    @classmethod
    def from_settings(cls) -> "SyncGpuRecoveryService":
        return cls(uow_factory=sync_gpu_execution_uow_factory, settings=settings)

    def recover_once(self) -> dict[str, int]:
        recovered = 0
        failed = 0
        canceled = 0
        with self._uow_factory() as uow:
            jobs = uow.jobs.list_stale_running(limit=self._settings.gpu_outbox_batch_size)
            for job in jobs:
                delay = timedelta(
                    seconds=self._settings.gpu_job_retry_base_seconds
                    * (2 ** max(job.attempt_count - 1, 0))
                )
                status = uow.jobs.recover_stale(job, retry_delay=delay)
                if status == GpuJobStatus.RETRYING:
                    delivery_key = f"gpu.execute:{job.id}:attempt:{job.attempt_count + 1}"
                    if uow.outbox_events.get_by_delivery_key(delivery_key) is None:
                        uow.outbox_events.add(
                            GpuOutboxEvent(
                                gpu_job_id=job.id,
                                delivery_key=delivery_key,
                                available_at=job.available_at,
                            )
                        )
                    recovered += 1
                elif status == GpuJobStatus.CANCELED:
                    canceled += 1
                else:
                    failed += 1
        return {"recovered": recovered, "failed": failed, "canceled": canceled}
