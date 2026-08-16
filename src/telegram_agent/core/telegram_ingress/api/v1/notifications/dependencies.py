from telegram_agent.core.telegram_ingress.clients.telegram_bot import TelegramBotClient
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.db.uow.async_uow_factory import (
    async_telegram_ingress_uow_factory,
)
from telegram_agent.core.telegram_ingress.services.async_user_notification import (
    AsyncUserNotificationService,
)


def get_user_notification_service() -> AsyncUserNotificationService:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured for notifications")
    return AsyncUserNotificationService(
        uow_factory=async_telegram_ingress_uow_factory,
        telegram_bot_client=TelegramBotClient(
            bot_token=settings.telegram_bot_token,
            api_base_url=settings.telegram_api_base_url,
        ),
    )
