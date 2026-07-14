from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.agent_runtime.common.types import ClaimStatus
from telegram_agent.core.agent_runtime.db.models.runtime import ConversationClaim
from telegram_agent.core.common.utils import utcnow


class AsyncSqlAlchemyConversationClaimRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure_idle(self, chat_id: int) -> ConversationClaim:
        statement = (
            insert(ConversationClaim)
            .values(
                chat_id=chat_id,
                status=ClaimStatus.IDLE,
                available_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["chat_id"])
            .returning(ConversationClaim)
        )
        result = await self._session.execute(statement)
        claim = result.scalar_one_or_none()
        if claim is not None:
            return claim

        existing = await self._session.execute(
            select(ConversationClaim).where(ConversationClaim.chat_id == chat_id)
        )
        claim = existing.scalar_one()
        return claim
