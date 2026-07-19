from telegram_agent.core.common.clients.telegram_auth import TelegramAuthClient
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.db.uow.async_uow_factory import async_content_processing_uow_factory
from telegram_agent.core.content_processing.services.async_download_request_service import (
    AsyncDownloadRequestService,
)
from telegram_agent.core.content_processing.services.async_telegram_job_service import AsyncTelegramJobService


def get_telegram_auth_client():
    return TelegramAuthClient(
        base_url=settings.telegram_auth_base_url,
        token=settings.auth_service_token,
    )


def get_telegram_job_service() -> AsyncTelegramJobService:
    return AsyncTelegramJobService(
        uow_factory=async_content_processing_uow_factory,
    )


def get_download_request_service() -> AsyncDownloadRequestService:
    return AsyncDownloadRequestService(
        uow_factory=async_content_processing_uow_factory,
    )