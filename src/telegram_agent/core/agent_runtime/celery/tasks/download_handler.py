from __future__ import annotations

from uuid import UUID

from celery.utils.log import get_task_logger

from telegram_agent.core.agent_runtime.celery.celery_app import celery_app
from telegram_agent.core.agent_runtime.services.sync_download_handler import (
    SyncDownloadHandlerService,
)

logger = get_task_logger(__name__)


@celery_app.task(name="agent_runtime.download_handler")
def download_handler_task(chat_id: int, claim_token: str) -> dict[str, object]:
    try:
        token = UUID(claim_token)
    except (TypeError, ValueError):
        logger.warning(
            "Ignoring download handler task with invalid claim token",
            extra={"chat_id": chat_id, "claim_token": claim_token},
        )
        return {"chat_id": chat_id, "processed": 0, "results": []}

    result = SyncDownloadHandlerService.from_settings().process_conversation(
        chat_id=chat_id,
        claim_token=token,
    )
    logger.info(
        "Processed download handler events",
        extra={"chat_id": chat_id, "processed": result.processed},
    )
    return {
        "chat_id": result.chat_id,
        "processed": result.processed,
        "results": [
            {
                "runtime_message_id": str(item.runtime_message_id),
                "status": item.status,
                "early_exit": item.early_exit,
                "agent_message_id": (
                    str(item.agent_message_id)
                    if item.agent_message_id is not None
                    else None
                ),
            }
            for item in result.results
        ],
    }
