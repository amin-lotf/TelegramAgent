from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.telegram_ingress.clients.content_processing import ContentProcessingClient
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.db.uow.async_uow_factory import async_telegram_ingress_uow_factory
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService

def get_content_processing_client():
    return ContentProcessingClient(
        base_url=settings.content_processing_base_url,
        token=settings.content_processing_service_token,
    )


def get_user_message_service() -> AsyncUserMessageService:
    return AsyncUserMessageService(
        uow_factory=async_telegram_ingress_uow_factory,
        content_processing_client=get_content_processing_client(),
    )




def get_telegram_auth_client():
    return TelegramAuthClient(
        base_url=settings.telegram_auth_base_url,
        token=settings.auth_service_token,
    )