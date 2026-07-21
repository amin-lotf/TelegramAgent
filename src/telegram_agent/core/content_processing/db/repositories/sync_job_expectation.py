from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from telegram_agent.core.common.utils import clean_error_message, utcnow
from telegram_agent.core.content_processing.common.types import (
    JobCompletionExpectationStatus,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    JobCompletionExpectation,
)

_RESOLVED_STATUSES = (
    JobCompletionExpectationStatus.SATISFIED,
    JobCompletionExpectationStatus.TIMED_OUT,
)


class SyncSqlAlchemyJobExpectationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, expectation: JobCompletionExpectation) -> JobCompletionExpectation:
        self._session.add(expectation)
        self._session.flush()
        return expectation

    def get_by_job_id(self, job_id: UUID) -> JobCompletionExpectation | None:
        return self._session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )

    def mark_satisfied(self, *, job_id: UUID) -> bool:
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.job_id == job_id,
                JobCompletionExpectation.status.in_(
                    (
                        JobCompletionExpectationStatus.OPEN,
                        JobCompletionExpectationStatus.PROCESSING,
                    )
                ),
            )
            .values(
                status=JobCompletionExpectationStatus.SATISFIED,
                resolved_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(JobCompletionExpectation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def extend_due_at(self, *, job_id: UUID, extra: timedelta) -> bool:
        """Push the SLA deadline forward for a still-open expectation.

        Used when a long stage (e.g. WhisperX on multi-hour media) is claimed so
        the sweeper does not kill in-flight work.
        """
        if extra.total_seconds() <= 0:
            return False
        now = utcnow()
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.job_id == job_id,
                JobCompletionExpectation.status.in_(
                    (
                        JobCompletionExpectationStatus.OPEN,
                        JobCompletionExpectationStatus.PROCESSING,
                    )
                ),
            )
            .values(
                # Never move due_at backwards; keep the farther of (now+extra, current).
                due_at=func.greatest(
                    JobCompletionExpectation.due_at,
                    now + extra,
                ),
                last_error=None,
            )
            .returning(JobCompletionExpectation.id)
        )
        return self._session.execute(statement).scalar_one_or_none() is not None

    def reopen_with_due_at(
        self,
        *,
        expectation_id: UUID,
        lease_owner: str,
        due_at: datetime,
    ) -> JobCompletionExpectation | None:
        """Release a claimed expectation back to open with a later due_at."""
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.id == expectation_id,
                JobCompletionExpectation.status
                == JobCompletionExpectationStatus.PROCESSING,
                JobCompletionExpectation.locked_by == lease_owner,
            )
            .values(
                status=JobCompletionExpectationStatus.OPEN,
                due_at=due_at,
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(JobCompletionExpectation)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_timed_out(
        self,
        *,
        expectation_id: UUID,
        lease_owner: str,
        error_message: str | None = None,
    ) -> JobCompletionExpectation | None:
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.id == expectation_id,
                JobCompletionExpectation.status
                == JobCompletionExpectationStatus.PROCESSING,
                JobCompletionExpectation.locked_by == lease_owner,
            )
            .values(
                status=JobCompletionExpectationStatus.TIMED_OUT,
                resolved_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=(
                    clean_error_message(error_message, max_length=2000)
                    if error_message
                    else None
                ),
            )
            .returning(JobCompletionExpectation)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def mark_satisfied_claimed(
        self,
        *,
        expectation_id: UUID,
        lease_owner: str,
    ) -> JobCompletionExpectation | None:
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.id == expectation_id,
                JobCompletionExpectation.status
                == JobCompletionExpectationStatus.PROCESSING,
                JobCompletionExpectation.locked_by == lease_owner,
            )
            .values(
                status=JobCompletionExpectationStatus.SATISFIED,
                resolved_at=func.now(),
                locked_at=None,
                locked_by=None,
                last_error=None,
            )
            .returning(JobCompletionExpectation)
        )
        return self._session.execute(statement).scalar_one_or_none()

    def claim_due(
        self,
        *,
        batch_size: int,
        lease_owner: str,
        lease_timeout: timedelta,
    ) -> list[JobCompletionExpectation]:
        now = utcnow()
        expired_before = now - lease_timeout

        locked_ids_stmt = (
            select(JobCompletionExpectation.id)
            .where(
                or_(
                    and_(
                        JobCompletionExpectation.status
                        == JobCompletionExpectationStatus.OPEN,
                        JobCompletionExpectation.due_at <= now,
                    ),
                    and_(
                        JobCompletionExpectation.status
                        == JobCompletionExpectationStatus.PROCESSING,
                        JobCompletionExpectation.locked_at < expired_before,
                    ),
                )
            )
            .order_by(
                JobCompletionExpectation.due_at,
                JobCompletionExpectation.created_at,
                JobCompletionExpectation.id,
            )
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        locked_ids = list(self._session.scalars(locked_ids_stmt).all())
        if not locked_ids:
            return []

        update_stmt = (
            update(JobCompletionExpectation)
            .where(JobCompletionExpectation.id.in_(locked_ids))
            .values(
                status=JobCompletionExpectationStatus.PROCESSING,
                locked_at=now,
                locked_by=lease_owner,
            )
            .returning(JobCompletionExpectation)
        )
        claimed_by_id = {
            expectation.id: expectation
            for expectation in self._session.execute(update_stmt).scalars().all()
        }
        return [
            claimed_by_id[expectation_id]
            for expectation_id in locked_ids
            if expectation_id in claimed_by_id
        ]

    def recover_expired_leases(self, *, lease_timeout: timedelta) -> int:
        expired_before = utcnow() - lease_timeout
        statement = (
            update(JobCompletionExpectation)
            .where(
                JobCompletionExpectation.status
                == JobCompletionExpectationStatus.PROCESSING,
                JobCompletionExpectation.locked_at < expired_before,
            )
            .values(
                status=JobCompletionExpectationStatus.OPEN,
                locked_at=None,
                locked_by=None,
            )
        )
        result = self._session.execute(statement)
        return int(cast(CursorResult, result).rowcount or 0)

    def delete_resolved(
        self,
        *,
        older_than: datetime,
        batch_size: int,
    ) -> int:
        ids_stmt = (
            select(JobCompletionExpectation.id)
            .where(
                JobCompletionExpectation.status.in_(_RESOLVED_STATUSES),
                JobCompletionExpectation.resolved_at.is_not(None),
                JobCompletionExpectation.resolved_at <= older_than,
            )
            .order_by(
                JobCompletionExpectation.resolved_at,
                JobCompletionExpectation.id,
            )
            .limit(batch_size)
        )
        ids = list(self._session.scalars(ids_stmt).all())
        if not ids:
            return 0

        result = self._session.execute(
            delete(JobCompletionExpectation).where(
                JobCompletionExpectation.id.in_(ids)
            )
        )
        return int(cast(CursorResult, result).rowcount or 0)
