import logging
from contextlib import AbstractAsyncContextManager
from typing import Callable
from telegram_agent.core.telegram_auth.common.commands import VerifyTelegramUserCommand
from telegram_agent.core.telegram_auth.db.uow.async_telegram_auth import SqlAlchemyTelegramAuthUnitOfWork
from telegram_agent.core.telegram_auth.security.telegram_user_password import password_matches

logger = logging.getLogger(__name__)


class UserAuthenticationService:
    def __init__(self,
                 uow_factory: Callable[[], AbstractAsyncContextManager[SqlAlchemyTelegramAuthUnitOfWork],]) -> None:
        self._uow_factory = uow_factory

    async def verify_user(
            self,
            command: VerifyTelegramUserCommand,

    ) -> bool:
        if not command.password or not password_matches(command.password):
            logger.warning("Invalid password for user %s", command.telegram_user_id)
            return False
        async with self._uow_factory() as uow:
            await uow.telegram_users.create_or_update_verified_user(
                telegram_user_id=command.telegram_user_id,
                chat_id=command.chat_id,
                username=command.username,
                first_name=command.first_name,
                last_name=command.last_name,
                is_bot=command.is_bot,
                language_code=command.language_code,
            )
        logger.info("User %s verified", command.telegram_user_id)
        return True

    async def check_user(self, telegram_user_id: int) -> bool:
        async with self._uow_factory() as uow:
            verified = await uow.telegram_users.is_verified(telegram_user_id)

            if verified:
                await uow.telegram_users.update_last_seen(telegram_user_id)
            logger.info("User %s is %s", telegram_user_id, "verified" if verified else "not verified")
            return verified

    async def revoke_user(self, telegram_user_id: int) -> bool:
        async with self._uow_factory() as uow:
                user = await uow.telegram_users.get_by_telegram_user_id(
                    telegram_user_id
                )

                if user is None:
                    return False

                await uow.telegram_users.revoke_user(telegram_user_id)
                return True
