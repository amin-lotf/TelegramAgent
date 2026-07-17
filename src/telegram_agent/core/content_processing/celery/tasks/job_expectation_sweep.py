from __future__ import annotations

from celery.utils.log import get_task_logger

from telegram_agent.core.content_processing.celery.celery_app import celery_app
from telegram_agent.core.content_processing.services.sync_job_expectation_sweeper import (
    SyncJobExpectationSweeper,
)

logger = get_task_logger(__name__)


@celery_app.task(name="job_expectations.sweep")
def sweep_job_expectations_task() -> dict[str, int]:
    result = SyncJobExpectationSweeper.from_settings().sweep_once()
    logger.info(
        "Completed job completion expectation sweep",
        extra={
            "claimed": result.claimed,
            "timed_out": result.timed_out,
            "satisfied": result.satisfied,
            "recovered_leases": result.recovered_leases,
            "deleted": result.deleted,
        },
    )
    return {
        "claimed": result.claimed,
        "timed_out": result.timed_out,
        "satisfied": result.satisfied,
        "recovered_leases": result.recovered_leases,
        "deleted": result.deleted,
    }
