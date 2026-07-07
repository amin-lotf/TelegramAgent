from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import logging
from telegram_agent.core.telegram_ingress.db.models.user_message import UserMessage

logger = logging.getLogger(__name__)

class SqlAlchemyUserMessageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, user_message: UserMessage) -> None:
        self._session.add(user_message)

    async def get_by_id(self, user_message_id: UUID) -> UserMessage | None:
        stmt = (
            select(UserMessage)
            .where(UserMessage.id == user_message_id)
            .options(selectinload(UserMessage.attachment))
        )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_chat_and_message_id(
            self,
            *,
            chat_id: int,
            message_id: int,
    ) -> UserMessage | None:
        stmt = (
            select(UserMessage)
            .where(
                UserMessage.chat_id == chat_id,
                UserMessage.message_id == message_id,
            )
            .options(selectinload(UserMessage.attachment))
        )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_update_id(self, update_id: int) -> UserMessage | None:
        stmt = (
            select(UserMessage)
            .where(UserMessage.update_id == update_id)
            .options(selectinload(UserMessage.attachment))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_existing(
            self,
            *,
            update_id: int | None,
            chat_id: int,
            message_id: int,
    ) -> UserMessage | None:
        if update_id is not None:
            existing = await self.get_by_update_id(update_id)
            if existing is not None:
                return existing

        return await self.get_by_chat_and_message_id(
            chat_id=chat_id,
            message_id=message_id,
        )