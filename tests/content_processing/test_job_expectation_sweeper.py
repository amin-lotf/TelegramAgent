from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.common.types import (
    JobCompletionExpectationKind,
    JobCompletionExpectationStatus,
    JobKind,
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    Job,
    JobCompletionExpectation,
    MediaAsset,
    OutboxEvent,
    TelegramSource,
)
from telegram_agent.core.content_processing.services.sync_job_expectation_sweeper import (
    SyncJobExpectationSweeper,
)


def _sweeper(
    content_sync_uow_factory,
    *,
    retention: timedelta = timedelta(0),
    active_grace: timedelta = timedelta(0),
):
    return SyncJobExpectationSweeper(
        uow_factory=content_sync_uow_factory,
        batch_size=50,
        lease_timeout=timedelta(seconds=60),
        resolved_retention=retention,
        active_grace=active_grace,
        lease_owner="test-sweeper",
    )


def test_sweeper_times_out_due_open_expectation(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.QUEUED,
        due_at=utcnow() - timedelta(seconds=5),
    )

    # Keep the timed_out row for assertion (retention > 0).
    result = _sweeper(
        content_sync_uow_factory,
        retention=timedelta(hours=1),
    ).sweep_once()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )
        finished = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.job_id == job_id,
                OutboxEvent.event_type
                == OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value,
            )
        )

    assert result.claimed == 1
    assert result.timed_out == 1
    assert job is not None and job.status == JobStatus.TIMED_OUT
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.TIMED_OUT
    assert finished is not None


def test_sweeper_satisfies_expectation_when_job_already_terminal(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.COMPLETED,
        due_at=utcnow() - timedelta(seconds=5),
    )

    result = _sweeper(
        content_sync_uow_factory,
        retention=timedelta(hours=1),
    ).sweep_once()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )
        finished_count = len(
            list(
                session.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.job_id == job_id,
                        OutboxEvent.event_type
                        == OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value,
                    )
                )
            )
        )

    assert result.claimed == 1
    assert result.satisfied == 1
    assert result.timed_out == 0
    assert job is not None and job.status == JobStatus.COMPLETED
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.SATISFIED
    assert finished_count == 0


def test_sweeper_extends_active_transcribing_job(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.TRANSCRIBING,
        due_at=utcnow() - timedelta(seconds=5),
    )

    result = _sweeper(
        content_sync_uow_factory,
        retention=timedelta(hours=1),
        active_grace=timedelta(hours=1),
    ).sweep_once()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )

    assert result.claimed == 1
    assert result.extended == 1
    assert result.timed_out == 0
    assert job is not None and job.status == JobStatus.TRANSCRIBING
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.OPEN
    assert expectation.due_at > utcnow()


def test_sweeper_ignores_not_yet_due_expectations(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.QUEUED,
        due_at=utcnow() + timedelta(hours=1),
    )

    result = _sweeper(content_sync_uow_factory).sweep_once()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )

    assert result.claimed == 0
    assert result.deleted == 0
    assert job is not None and job.status == JobStatus.QUEUED
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.OPEN


def test_sweeper_purges_resolved_expectations(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    satisfied_job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.COMPLETED,
        due_at=utcnow() - timedelta(minutes=5),
        expectation_status=JobCompletionExpectationStatus.SATISFIED,
        resolved_at=utcnow() - timedelta(minutes=1),
    )
    timed_out_job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.TIMED_OUT,
        due_at=utcnow() - timedelta(minutes=5),
        expectation_status=JobCompletionExpectationStatus.TIMED_OUT,
        resolved_at=utcnow() - timedelta(minutes=1),
    )
    open_job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.QUEUED,
        due_at=utcnow() + timedelta(hours=1),
    )

    result = _sweeper(content_sync_uow_factory).sweep_once()

    with content_sync_sessionmaker() as session:
        remaining = {
            row.job_id: row.status
            for row in session.scalars(select(JobCompletionExpectation)).all()
        }

    assert result.deleted == 2
    assert satisfied_job_id not in remaining
    assert timed_out_job_id not in remaining
    assert remaining[open_job_id] == JobCompletionExpectationStatus.OPEN


def test_sweeper_respects_resolved_retention(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.COMPLETED,
        due_at=utcnow() - timedelta(minutes=5),
        expectation_status=JobCompletionExpectationStatus.SATISFIED,
        resolved_at=utcnow(),
    )

    result = _sweeper(
        content_sync_uow_factory,
        retention=timedelta(hours=1),
    ).sweep_once()

    with content_sync_sessionmaker() as session:
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )

    assert result.deleted == 0
    assert expectation is not None
    assert expectation.status == JobCompletionExpectationStatus.SATISFIED


def test_sweeper_with_zero_retention_deletes_just_timed_out_row(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_job_with_expectation(
        content_sync_sessionmaker,
        job_status=JobStatus.QUEUED,
        due_at=utcnow() - timedelta(seconds=5),
    )

    result = _sweeper(content_sync_uow_factory).sweep_once()

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)
        expectation = session.scalar(
            select(JobCompletionExpectation).where(
                JobCompletionExpectation.job_id == job_id
            )
        )
        finished = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.job_id == job_id,
                OutboxEvent.event_type
                == OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED.value,
            )
        )

    assert result.timed_out == 1
    assert result.deleted >= 1
    assert job is not None and job.status == JobStatus.TIMED_OUT
    assert expectation is None
    assert finished is not None


def _seed_job_with_expectation(
    content_sync_sessionmaker: sessionmaker[Session],
    *,
    job_status: JobStatus,
    due_at,
    expectation_status: JobCompletionExpectationStatus = JobCompletionExpectationStatus.OPEN,
    resolved_at=None,
):
    job_id = uuid4()
    with content_sync_sessionmaker() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=job_status,
                idempotency_key=f"expectation-{job_id}",
                callback_required=True,
            )
        )
        session.add(
            TelegramSource(
                job_id=job_id,
                ingress_message_id=uuid4(),
                ingress_attachment_id=uuid4(),
                telegram_user_id=1,
                telegram_file_id="file",
                telegram_file_unique_id="unique",
                attachment_type=TelegramAttachmentType.VOICE,
            )
        )
        session.add(
            MediaAsset(
                job_id=job_id,
                role=MediaAssetRole.SOURCE,
                media_type=TelegramAttachmentType.VOICE.value,
                local_path=None,
            )
        )
        session.add(
            JobCompletionExpectation(
                job_id=job_id,
                kind=JobCompletionExpectationKind.JOB_COMPLETION,
                status=expectation_status,
                due_at=due_at,
                resolved_at=resolved_at,
            )
        )
        session.commit()
    return job_id
