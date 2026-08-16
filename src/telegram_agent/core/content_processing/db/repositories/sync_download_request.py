from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
)
from telegram_agent.core.content_processing.common.types import DownloadDeliveryStatus
from telegram_agent.core.common.utils import clean_error_message, utcnow


class SyncSqlAlchemyDownloadRequestRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_job_id(self, job_id: UUID) -> DownloadRequest | None:
        return self._session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == job_id)
        )

    def set_final_path(self, *, job_id: UUID, final_path: str) -> bool:
        statement = (
            update(DownloadRequest)
            .where(DownloadRequest.job_id == job_id)
            .values(final_path=final_path, updated_at=func.now())
            .returning(DownloadRequest.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def claim_delivery(
        self, *, job_id: UUID, lease_timeout: timedelta
    ) -> DownloadRequest | None:
        stale_before = utcnow() - lease_timeout
        statement = (
            update(DownloadRequest)
            .where(
                DownloadRequest.job_id == job_id,
                or_(
                    DownloadRequest.delivery_status == DownloadDeliveryStatus.PENDING,
                    (
                        (DownloadRequest.delivery_status == DownloadDeliveryStatus.SENDING)
                        & (DownloadRequest.updated_at < stale_before)
                    ),
                ),
            )
            .values(
                delivery_status=DownloadDeliveryStatus.SENDING,
                delivery_error=None,
                updated_at=func.now(),
            )
            .returning(DownloadRequest)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_delivery_pending(self, *, job_id: UUID, error_message: str) -> None:
        self._session.execute(
            update(DownloadRequest)
            .where(
                DownloadRequest.job_id == job_id,
                DownloadRequest.delivery_status == DownloadDeliveryStatus.SENDING,
            )
            .values(
                delivery_status=DownloadDeliveryStatus.PENDING,
                delivery_attempt_count=DownloadRequest.delivery_attempt_count + 1,
                delivery_error=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
        )

    def mark_delivery_failed(self, *, job_id: UUID, error_message: str) -> None:
        self._session.execute(
            update(DownloadRequest)
            .where(
                DownloadRequest.job_id == job_id,
                DownloadRequest.delivery_status.in_(
                    (DownloadDeliveryStatus.PENDING, DownloadDeliveryStatus.SENDING)
                ),
            )
            .values(
                delivery_status=DownloadDeliveryStatus.FAILED,
                delivery_attempt_count=DownloadRequest.delivery_attempt_count + 1,
                delivery_error=clean_error_message(error_message, max_length=2000),
                updated_at=func.now(),
            )
        )

    def mark_delivered(self, *, job_id: UUID, telegram_message_id: int) -> bool:
        statement = (
            update(DownloadRequest)
            .where(
                DownloadRequest.job_id == job_id,
                DownloadRequest.delivery_status == DownloadDeliveryStatus.SENDING,
            )
            .values(
                delivery_status=DownloadDeliveryStatus.DELIVERED,
                delivery_attempt_count=DownloadRequest.delivery_attempt_count + 1,
                delivery_error=None,
                telegram_delivery_message_id=telegram_message_id,
                delivered_at=func.now(),
                updated_at=func.now(),
            )
            .returning(DownloadRequest.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None
