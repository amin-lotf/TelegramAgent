from __future__ import annotations

import os
import socket
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable

from celery import Celery

from telegram_agent.core.gpu_execution.common.settings import Settings, settings
from telegram_agent.core.gpu_execution.db.uow.sync_gpu_execution import SyncSqlAlchemyGpuExecutionUnitOfWork
from telegram_agent.core.gpu_execution.db.uow.sync_uow_factory import sync_gpu_execution_uow_factory


class SyncGpuOutboxDispatcher:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], AbstractContextManager[SyncSqlAlchemyGpuExecutionUnitOfWork]],
        celery_app: Celery,
        settings: Settings,
        lease_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._celery_app = celery_app
        self._settings = settings
        self._lease_owner = lease_owner or f"{socket.gethostname()}:{os.getpid()}"

    @classmethod
    def from_settings(cls, celery_app: Celery) -> "SyncGpuOutboxDispatcher":
        return cls(
            uow_factory=sync_gpu_execution_uow_factory,
            celery_app=celery_app,
            settings=settings,
        )

    def dispatch_once(self) -> dict[str, int]:
        with self._uow_factory() as uow:
            events = uow.outbox_events.claim_available(
                batch_size=self._settings.gpu_outbox_batch_size,
                lease_owner=self._lease_owner,
                lease_timeout=timedelta(seconds=self._settings.gpu_outbox_lease_seconds),
            )

        published = 0
        failed = 0
        for event in events:
            try:
                self._celery_app.send_task(
                    "gpu.execute",
                    args=(str(event.gpu_job_id),),
                    queue="gpu_execution",
                    routing_key="gpu.execute",
                )
            except Exception as exc:
                failed += 1
                with self._uow_factory() as uow:
                    uow.outbox_events.record_failure(
                        event_id=event.id,
                        lease_owner=self._lease_owner,
                        error_message=str(exc),
                        retry_delay=timedelta(seconds=self._settings.gpu_job_retry_base_seconds),
                    )
                continue
            with self._uow_factory() as uow:
                if uow.outbox_events.mark_published(
                    event_id=event.id,
                    lease_owner=self._lease_owner,
                ):
                    published += 1
        return {"claimed": len(events), "published": published, "failed": failed}
