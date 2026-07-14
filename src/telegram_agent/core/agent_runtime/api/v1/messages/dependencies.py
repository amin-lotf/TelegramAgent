from telegram_agent.core.agent_runtime.db.uow.async_uow_factory import (
    async_agent_runtime_uow_factory,
)
from telegram_agent.core.agent_runtime.services.async_message_batch_ingestion import (
    AsyncMessageBatchIngestionService,
)


def get_message_batch_ingestion_service() -> AsyncMessageBatchIngestionService:
    return AsyncMessageBatchIngestionService(
        uow_factory=async_agent_runtime_uow_factory,
    )
