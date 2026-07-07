from telegram_agent.core.telegram_ingress.db.uow.async_uow_factory import async_telegram_ingress_uow_factory
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService


def get_user_message_service() -> AsyncUserMessageService:
    return AsyncUserMessageService(
        uow_factory=async_telegram_ingress_uow_factory,
    )