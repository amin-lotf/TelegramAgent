from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.telegram_auth.db.models.telegram_user import TelegramUser


class SqlAlchemyTelegramUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_user_id(
        self,
        telegram_user_id: int,
    ) -> TelegramUser | None:
        stmt = select(TelegramUser).where(
            TelegramUser.telegram_user_id == telegram_user_id
        )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def is_verified(
        self,
        telegram_user_id: int,
    ) -> bool:
        stmt = select(TelegramUser.id).where(
            TelegramUser.telegram_user_id == telegram_user_id,
            TelegramUser.is_active.is_(True),
        )

        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def create_or_update_verified_user(
        self,
        *,
        telegram_user_id: int,
        chat_id: int,
        username: str | None,
        first_name: str | None,
        last_name: str | None,
        is_bot: bool,
        language_code: str | None,
    ) -> TelegramUser:
        user = await self.get_by_telegram_user_id(telegram_user_id)

        if user is None:
            user = TelegramUser(
                telegram_user_id=telegram_user_id,
                chat_id=chat_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_bot=is_bot,
                language_code=language_code,
                is_active=True,
            )
            self._session.add(user)
        else:
            user.chat_id = chat_id
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
            user.is_bot = is_bot
            user.language_code = language_code
            user.is_active = True
            user.last_seen_at = utcnow()

        await self._session.flush()
        return user

    async def update_last_seen(
        self,
        telegram_user_id: int,
    ) -> None:
        stmt = (
            update(TelegramUser)
            .where(TelegramUser.telegram_user_id == telegram_user_id)
            .values(last_seen_at=utcnow())
        )

        await self._session.execute(stmt)

    async def revoke_user(
        self,
        telegram_user_id: int,
    ) -> None:
        stmt = (
            update(TelegramUser)
            .where(TelegramUser.telegram_user_id == telegram_user_id)
            .values(is_active=False)
        )

        await self._session.execute(stmt)