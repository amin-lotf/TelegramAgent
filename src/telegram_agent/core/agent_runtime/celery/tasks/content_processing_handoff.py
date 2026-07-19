from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.agent_runtime.celery.celery_app import celery_app
from telegram_agent.core.agent_runtime.services.sync_content_processing_handoff import (
    SyncContentProcessingHandoffService,
)

logger = get_task_logger(__name__)


@celery_app.task(name="agent_runtime.content_processing_handoff")
def content_processing_handoff_task(
    chat_id: int,
    claim_token: str,
) -> dict[str, object]:
    try:
        token = UUID(claim_token)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring content-processing handoff task with invalid claim token",
            extra={"chat_id": chat_id, "claim_token": claim_token},
        )
        return {"chat_id": chat_id, "processed": 0, "results": []}

    result = SyncContentProcessingHandoffService.from_settings().process_conversation(
        chat_id=chat_id,
        claim_token=token,
    )
    logger.info(
        "Processed content-processing handoff events",
        extra={"chat_id": chat_id, "processed": result.processed},
    )
    return {
        "chat_id": result.chat_id,
        "processed": result.processed,
        "results": [
            {
                "runtime_message_id": str(item.runtime_message_id),
                "status": item.status,
            }
            for item in result.results
        ],
    }
