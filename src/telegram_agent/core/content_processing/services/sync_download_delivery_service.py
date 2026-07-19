from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    PermanentContentProcessingError,
    RetryableContentProcessingError,
    TelegramDownloadError,
    TelegramDownloadPermanentError,
)
from telegram_agent.core.content_processing.clients.telegram_client import TelegramClient
from telegram_agent.core.content_processing.common.results import StageExecutionResult
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import DownloadMediaType
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


class SyncDownloadDeliveryService:
    """Deliver a prepared download file to the user via Telegram Bot API."""

    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
        telegram_client: TelegramClient | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._telegram_client = telegram_client

    @classmethod
    def from_settings(cls) -> "SyncDownloadDeliveryService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
        )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        try:
            with self._uow_factory() as uow:
                request = uow.download_requests.get_by_job_id(job_id)
                if request is None:
                    raise PermanentContentProcessingError(
                        "Download request record is missing for delivery"
                    )
                if not request.final_path:
                    raise PermanentContentProcessingError(
                        "Download final_path is not set for delivery"
                    )
                chat_id = request.chat_id
                media_type = request.media_type
                final_path = request.final_path
                caption = request.assistant_text

            client = self._telegram_client or TelegramClient(self._settings)
            self._send(
                client=client,
                media_type=media_type,
                chat_id=chat_id,
                final_path=final_path,
                caption=caption,
            )
            return StageExecutionResult()
        except PermanentContentProcessingError as exc:
            return StageExecutionResult(error_message=str(exc))
        except TelegramDownloadPermanentError as exc:
            return StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, TelegramDownloadError, SQLAlchemyError) as exc:
            if retry_count >= self._settings.media_task_max_retries:
                return StageExecutionResult(
                    error_message="Download delivery retry limit exhausted"
                )
            return StageExecutionResult(retryable=True, error_message=str(exc))

    @staticmethod
    def _send(
        *,
        client: TelegramClient,
        media_type: str,
        chat_id: int,
        final_path: str,
        caption: str | None,
    ) -> None:
        # MKV (and other non-MP4 containers) must go as documents; sendVideo
        # only reliably accepts progressive MP4.
        suffix = final_path.rsplit(".", 1)[-1].lower() if "." in final_path else ""
        if suffix in {"mkv", "webm", "avi", "mov"}:
            client.send_document(chat_id=chat_id, file_path=final_path, caption=caption)
            return
        if media_type == DownloadMediaType.VIDEO.value:
            client.send_video(chat_id=chat_id, file_path=final_path, caption=caption)
            return
        if media_type == DownloadMediaType.AUDIO.value:
            client.send_audio(chat_id=chat_id, file_path=final_path, caption=caption)
            return
        if media_type == DownloadMediaType.DOCUMENT.value:
            client.send_document(chat_id=chat_id, file_path=final_path, caption=caption)
            return
        client.send_document(chat_id=chat_id, file_path=final_path, caption=caption)
