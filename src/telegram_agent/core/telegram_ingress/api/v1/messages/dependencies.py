from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.db.uow.async_uow_factory import async_telegram_ingress_uow_factory
from telegram_agent.core.telegram_ingress.security.telegram_auth_client import TelegramAuthClient
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService


def get_user_message_service() -> AsyncUserMessageService:
    return AsyncUserMessageService(
        uow_factory=async_telegram_ingress_uow_factory,
    )


def get_telegram_auth_client():
    return TelegramAuthClient(
        base_url=settings.telegram_auth_base_url,
        token=settings.auth_service_token,
    )