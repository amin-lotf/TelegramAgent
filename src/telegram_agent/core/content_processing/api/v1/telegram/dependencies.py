from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.content_processing.common.settings import settings


def get_telegram_auth_client():
    return TelegramAuthClient(
        base_url=settings.telegram_auth_base_url,
        token=settings.auth_service_token,
    )