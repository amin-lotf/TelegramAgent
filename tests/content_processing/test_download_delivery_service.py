from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import TelegramDownloadError
from telegram_agent.core.content_processing.common.results import TelegramDeliveryResult
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    DownloadMediaType,
    JobKind,
    JobStatus,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    Job,
)
from telegram_agent.core.content_processing.services.sync_download_delivery_service import (
    SyncDownloadDeliveryService,
)


class _Telegram:
    def __init__(self, *, fail_once: bool = False) -> None:
        self.fail_once = fail_once
        self.media_calls = 0
        self.media_methods: list[str] = []
        self.media_kwargs: list[dict] = []
        self.messages: list[dict] = []

    def _send_media(self, method: str, **kwargs) -> TelegramDeliveryResult:
        self.media_calls += 1
        self.media_methods.append(method)
        self.media_kwargs.append(kwargs)
        if self.fail_once:
            self.fail_once = False
            raise TelegramDownloadError("temporary Telegram failure")
        return TelegramDeliveryResult(message_id=321)

    def send_document(self, **kwargs) -> TelegramDeliveryResult:
        return self._send_media("send_document", **kwargs)

    def send_video(self, **kwargs) -> TelegramDeliveryResult:
        return self._send_media("send_video", **kwargs)

    def send_audio(self, **kwargs) -> TelegramDeliveryResult:
        return self._send_media("send_audio", **kwargs)

    def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> TelegramDeliveryResult:
        assert chat_id == 99
        self.messages.append(
            {"text": text, "reply_to_message_id": reply_to_message_id}
        )
        return TelegramDeliveryResult(message_id=654)


def test_delivery_is_persisted_and_duplicate_task_is_a_noop(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "dubbed.mp4"
    final_path.write_bytes(b"media")
    job_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        final_path=str(final_path),
        reply_to_message_id=42,
    )
    telegram = _Telegram()
    service = SyncDownloadDeliveryService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        telegram_client=telegram,  # type: ignore[arg-type]
    )

    assert service.execute(job_id=job_id, retry_count=0).error_message is None
    assert service.execute(job_id=job_id, retry_count=0).error_message is None
    assert telegram.media_calls == 1
    assert telegram.media_methods == ["send_video"]
    assert telegram.media_kwargs[0]["caption"] == "Video with es dub"
    assert telegram.media_kwargs[0]["reply_to_message_id"] == 42
    # Preparing/status text must not be used as the media caption.
    assert telegram.media_kwargs[0]["caption"] != "Here is your dub"
    with content_sync_sessionmaker() as session:
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )
    assert request is not None
    assert request.delivery_status == DownloadDeliveryStatus.DELIVERED
    assert request.telegram_delivery_message_id == 321
    assert request.delivery_attempt_count == 1


def test_retryable_delivery_returns_to_pending_and_can_resume(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "dubbed.mp4"
    final_path.write_bytes(b"media")
    job_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        final_path=str(final_path),
    )
    telegram = _Telegram(fail_once=True)
    service = SyncDownloadDeliveryService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        telegram_client=telegram,  # type: ignore[arg-type]
    )

    first = service.execute(job_id=job_id, retry_count=0)
    second = service.execute(job_id=job_id, retry_count=1)
    assert first.retryable is True
    assert second.error_message is None
    with content_sync_sessionmaker() as session:
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )
    assert request is not None
    assert request.delivery_status == DownloadDeliveryStatus.DELIVERED
    assert request.delivery_attempt_count == 2


def test_cancelled_download_uses_delivery_worker_for_user_notification(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.CANCELLED,
        final_path=None,
        reply_to_message_id=77,
    )
    telegram = _Telegram()
    service = SyncDownloadDeliveryService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        telegram_client=telegram,  # type: ignore[arg-type]
    )

    result = service.execute(job_id=job_id, retry_count=0)
    assert result.error_message is None
    assert telegram.messages == [
        {
            "text": "The download request was cancelled.",
            "reply_to_message_id": 77,
        }
    ]
    with content_sync_sessionmaker() as session:
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )
    assert request is not None
    assert request.delivery_status == DownloadDeliveryStatus.DELIVERED
    assert request.telegram_delivery_message_id == 654


def test_subtitle_delivery_caption(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "subs.mp4"
    final_path.write_bytes(b"media")
    job_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        final_path=str(final_path),
        requested_dub_language=None,
        requested_subtitle_language="English",
        media_type=DownloadMediaType.VIDEO.value,
    )
    telegram = _Telegram()
    service = SyncDownloadDeliveryService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        telegram_client=telegram,  # type: ignore[arg-type]
    )
    assert service.execute(job_id=job_id, retry_count=0).error_message is None
    assert telegram.media_methods == ["send_video"]
    assert telegram.media_kwargs[0]["caption"] == "Video with English subtitles"


def test_mkv_video_is_still_sent_as_document(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    final_path = tmp_path / "legacy.mkv"
    final_path.write_bytes(b"media")
    job_id = _seed_request(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        final_path=str(final_path),
        requested_dub_language=None,
        requested_subtitle_language="English",
        media_type=DownloadMediaType.VIDEO.value,
    )
    telegram = _Telegram()
    service = SyncDownloadDeliveryService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        telegram_client=telegram,  # type: ignore[arg-type]
    )
    assert service.execute(job_id=job_id, retry_count=0).error_message is None
    assert telegram.media_methods == ["send_document"]


def _seed_request(
    sessionmaker_factory: sessionmaker[Session],
    *,
    status: JobStatus,
    final_path: str | None,
    reply_to_message_id: int | None = None,
    requested_dub_language: str | None = "es",
    requested_subtitle_language: str | None = None,
    media_type: str = DownloadMediaType.VIDEO.value,
):
    job_id = uuid4()
    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.DOWNLOAD_PREPARATION,
                status=status,
                idempotency_key=f"delivery-{job_id}",
                callback_required=False,
                error_message="model failed" if status == JobStatus.FAILED else None,
            )
        )
        session.flush()
        session.add(
            DownloadRequest(
                job_id=job_id,
                chat_id=99,
                telegram_user_id=7,
                group_id=uuid4(),
                agent_message_id=uuid4(),
                media_ingress_message_id=uuid4(),
                media_type=media_type,
                requested_dub_language=requested_dub_language,
                requested_subtitle_language=requested_subtitle_language,
                assistant_text="Here is your dub",
                reply_to_message_id=reply_to_message_id,
                final_path=final_path,
            )
        )
        session.commit()
    return job_id
