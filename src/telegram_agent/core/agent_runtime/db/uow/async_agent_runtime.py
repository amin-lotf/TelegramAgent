from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.agent_runtime.db.repositories.async_batch import (
    AsyncSqlAlchemyRuntimeBatchRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.async_claim import (
    AsyncSqlAlchemyConversationClaimRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.async_message import (
    AsyncSqlAlchemyRuntimeMessageRepository,
)
from telegram_agent.core.agent_runtime.db.repositories.async_outbox import (
    AsyncSqlAlchemyOutboxRepository,
)


class AsyncSqlAlchemyAgentRuntimeUnitOfWork:
    def __init__(self, session: AsyncSession):
        self._session = session
        self.batches = AsyncSqlAlchemyRuntimeBatchRepository(session)
        self.messages = AsyncSqlAlchemyRuntimeMessageRepository(session)
        self.outbox_events = AsyncSqlAlchemyOutboxRepository(session)
        self.conversation_claims = AsyncSqlAlchemyConversationClaimRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def flush(self) -> None:
        await self._session.flush()

    async def __aenter__(self) -> "AsyncSqlAlchemyAgentRuntimeUnitOfWork":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if exc_type:
            await self.rollback()
        else:
            await self.commit()
