from telegram_agent.core.telegram_auth.db.uow.uow_factory import telegram_auth_uow_factory
from telegram_agent.core.telegram_auth.services.user_authentication import UserAuthenticationService


def get_telegram_auth_service() -> UserAuthenticationService:
    return UserAuthenticationService(
        uow_factory=telegram_auth_uow_factory,
    )