from __future__ import annotations

from telegram_agent.core.agent_runtime.celery.celery_app import celery_app
from telegram_agent.core.agent_runtime.services.coordination_outbox_dispatcher import (
    CoordinationOutboxDispatcher,
)


@celery_app.task(name="coordination.outbox.dispatch")
def dispatch_coordination_outbox_task() -> dict[str, int]:
    result = CoordinationOutboxDispatcher.from_settings().dispatch_once()
    return {
        "claimed": result.claimed,
        "published": result.published,
        "retryable_failures": result.retryable_failures,
        "permanent_failures": result.permanent_failures,
    }
