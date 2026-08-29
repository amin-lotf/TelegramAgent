from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.content_processing.common.cancellation import (
    secondary_task_scope_lock_key,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    SecondaryTaskCancellation,
)


class AsyncSqlAlchemySecondaryTaskCancellationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_scope(self, *, telegram_user_id: int, chat_id: int) -> None:
        lock_key = secondary_task_scope_lock_key(
            telegram_user_id=telegram_user_id,
            chat_id=chat_id,
        )
        await self._session.execute(select(func.pg_advisory_xact_lock(lock_key)))

    async def find_covering(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        request_message_id: int,
    ) -> SecondaryTaskCancellation | None:
        result = await self._session.execute(
            select(SecondaryTaskCancellation)
            .where(
                SecondaryTaskCancellation.telegram_user_id == telegram_user_id,
                SecondaryTaskCancellation.chat_id == chat_id,
                SecondaryTaskCancellation.cutoff_message_id > request_message_id,
            )
            .order_by(desc(SecondaryTaskCancellation.cutoff_message_id))
            .limit(1)
        )
        return result.scalar_one_or_none()
