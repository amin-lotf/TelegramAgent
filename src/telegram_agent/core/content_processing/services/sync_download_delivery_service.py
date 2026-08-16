from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from datetime import timedelta
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
from telegram_agent.core.content_processing.common.results import (
    StageExecutionResult,
    TelegramDeliveryResult,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    DownloadMediaType,
    JobStatus,
)
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)
from telegram_agent.core.content_processing.services.download_delivery_caption import (
    build_download_delivery_caption,
)


logger = logging.getLogger(__name__)


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
        self._delivery_lease = timedelta(seconds=60)

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
                request = uow.download_requests.claim_delivery(
                    job_id=job_id,
                    lease_timeout=self._delivery_lease,
                )
                if request is None:
                    existing = uow.download_requests.get_by_job_id(job_id)
                    if existing is None:
                        raise PermanentContentProcessingError(
                            "Download request record is missing for delivery"
                        )
                    if existing.delivery_status in (
                        DownloadDeliveryStatus.DELIVERED,
                        DownloadDeliveryStatus.FAILED,
                    ):
                        return StageExecutionResult()
                    return StageExecutionResult(
                        retryable=True,
                        error_message="Download delivery is already in progress",
                    )
                job = uow.jobs.get_by_id(job_id)
                if job is None:
                    raise PermanentContentProcessingError(
                        "Download job record is missing for delivery"
                    )
                chat_id = request.chat_id
                media_type = request.media_type
                final_path = request.final_path
                reply_to_message_id = request.reply_to_message_id
                # Status/preparing text lives on assistant_text and is sent earlier
                # as a standalone reply. Final media uses a short delivery caption.
                caption = build_download_delivery_caption(
                    media_type=media_type,
                    requested_subtitle_language=request.requested_subtitle_language,
                    requested_dub_language=request.requested_dub_language,
                    requested_language=request.requested_language,
                    requested_format=request.requested_format,
                )
                job_status = job.status
                job_error = job.error_message

            client = self._telegram_client or TelegramClient(self._settings)
            if job_status == JobStatus.COMPLETED:
                if not final_path:
                    raise PermanentContentProcessingError(
                        "Download final_path is not set for delivery"
                    )
                result = self._send(
                    client=client,
                    media_type=media_type,
                    chat_id=chat_id,
                    final_path=final_path,
                    caption=caption,
                    reply_to_message_id=reply_to_message_id,
                )
            elif job_status in (
                JobStatus.FAILED,
                JobStatus.CANCELLED,
                JobStatus.TIMED_OUT,
            ):
                result = client.send_message(
                    chat_id=chat_id,
                    text=self._failure_message(job_status, job_error),
                    reply_to_message_id=reply_to_message_id,
                )
            else:
                raise RetryableContentProcessingError(
                    f"Download job is not terminal: {job_status.value}"
                )

            with self._uow_factory() as uow:
                if not uow.download_requests.mark_delivered(
                    job_id=job_id,
                    telegram_message_id=result.message_id,
                ):
                    raise RetryableContentProcessingError(
                        "Unable to persist Telegram delivery completion"
                    )
            return StageExecutionResult()
        except PermanentContentProcessingError as exc:
            self._mark_failed(job_id, str(exc))
            return StageExecutionResult(error_message=str(exc))
        except TelegramDownloadPermanentError as exc:
            self._mark_failed(job_id, str(exc))
            return StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, TelegramDownloadError, SQLAlchemyError) as exc:
            if retry_count >= self._settings.media_task_max_retries:
                self._mark_failed(job_id, str(exc))
                return StageExecutionResult(
                    error_message="Download delivery retry limit exhausted"
                )
            self._mark_pending(job_id, str(exc))
            return StageExecutionResult(retryable=True, error_message=str(exc))

    @staticmethod
    def _send(
        *,
        client: TelegramClient,
        media_type: str,
        chat_id: int,
        final_path: str,
        caption: str | None,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        # MKV (and other non-MP4 containers) must go as documents; sendVideo
        # only reliably accepts progressive MP4.
        suffix = final_path.rsplit(".", 1)[-1].lower() if "." in final_path else ""
        send_kwargs = {
            "chat_id": chat_id,
            "file_path": final_path,
            "caption": caption,
            "reply_to_message_id": reply_to_message_id,
        }
        if suffix in {"mkv", "webm", "avi", "mov"}:
            return client.send_document(**send_kwargs)
        if media_type == DownloadMediaType.VIDEO.value:
            return client.send_video(**send_kwargs)
        if media_type == DownloadMediaType.AUDIO.value:
            return client.send_audio(**send_kwargs)
        if media_type == DownloadMediaType.DOCUMENT.value:
            return client.send_document(**send_kwargs)
        return client.send_document(**send_kwargs)

    def _mark_pending(self, job_id: UUID, error_message: str) -> None:
        try:
            with self._uow_factory() as uow:
                uow.download_requests.mark_delivery_pending(
                    job_id=job_id, error_message=error_message
                )
        except SQLAlchemyError:
            logger.warning(
                "Unable to return Telegram delivery to pending state",
                extra={"job_id": str(job_id)},
                exc_info=True,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        try:
            with self._uow_factory() as uow:
                uow.download_requests.mark_delivery_failed(
                    job_id=job_id, error_message=error_message
                )
        except SQLAlchemyError:
            logger.warning(
                "Unable to persist terminal Telegram delivery failure",
                extra={"job_id": str(job_id)},
                exc_info=True,
            )

    @staticmethod
    def _failure_message(status: JobStatus, error_message: str | None) -> str:
        if status == JobStatus.CANCELLED:
            return "The download request was cancelled."
        if status == JobStatus.TIMED_OUT:
            return "The download request timed out before it could be completed."
        detail = (error_message or "The download pipeline failed").strip()
        return f"I couldn't prepare the media: {detail[:1000]}"
