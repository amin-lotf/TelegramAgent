from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable
from uuid import UUID

from telegram_agent.core.content_processing.common.results import StageExecutionResult
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
    sync_content_processing_uow_factory,
)
from telegram_agent.core.content_processing.services.sync_dubbing_workflow_service import (
    SyncDubbingWorkflowService,
)
from telegram_agent.core.content_processing.services.sync_secondary_task_cancellation_service import (
    SyncSecondaryTaskCancellationService,
)


class SyncDownloadCancellationWorker:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [], AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork]
        ],
        cancellation_service: SyncSecondaryTaskCancellationService,
        dubbing_service: SyncDubbingWorkflowService,
    ) -> None:
        self._uow_factory = uow_factory
        self._cancellation_service = cancellation_service
        self._dubbing_service = dubbing_service

    @classmethod
    def from_settings(cls) -> "SyncDownloadCancellationWorker":
        return cls(
            uow_factory=sync_content_processing_uow_factory,
            cancellation_service=SyncSecondaryTaskCancellationService.from_settings(),
            dubbing_service=SyncDubbingWorkflowService.from_settings(),
        )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        with self._uow_factory() as uow:
            workflow_exists = uow.dubbing.get_by_job_id(job_id) is not None
        if workflow_exists:
            result = self._dubbing_service.execute(
                job_id=job_id,
                retry_count=retry_count,
            )
            if result.retryable or result.deferred:
                return result
        self._cancellation_service.finalize(job_id=job_id)
        return StageExecutionResult()
