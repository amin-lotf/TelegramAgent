from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.telegram_ingress.clients.content_processing import ContentProcessingClient
from telegram_agent.core.telegram_ingress.common.settings import settings
from telegram_agent.core.telegram_ingress.db.uow.async_uow_factory import (
    async_telegram_ingress_uow_factory,
)
from telegram_agent.core.telegram_ingress.services.async_attachment_processing_result import (
    AsyncAttachmentProcessingResultService,
)
from telegram_agent.core.telegram_ingress.services.async_user_message import AsyncUserMessageService
from telegram_agent.core.telegram_ingress.services.conversation_coordinator import ConversationCoordinator


def get_conversation_coordinator() -> ConversationCoordinator:
    return ConversationCoordinator(
        uow_factory=async_telegram_ingress_uow_factory,
    )


def get_content_processing_client() -> ContentProcessingClient:
    return ContentProcessingClient(
        base_url=settings.content_processing_base_url,
        token=settings.content_processing_service_token,
    )


def get_user_message_service() -> AsyncUserMessageService:
    return AsyncUserMessageService(
        uow_factory=async_telegram_ingress_uow_factory,
        content_processing_client=get_content_processing_client(),
        conversation_coordinator=get_conversation_coordinator(),
    )


def get_attachment_processing_result_service() -> AsyncAttachmentProcessingResultService:
    return AsyncAttachmentProcessingResultService(
        uow_factory=async_telegram_ingress_uow_factory,
        conversation_coordinator=get_conversation_coordinator(),
    )


def get_telegram_auth_client() -> TelegramAuthClient:
    return TelegramAuthClient(
        base_url=settings.telegram_auth_base_url,
        token=settings.auth_service_token,
    )
