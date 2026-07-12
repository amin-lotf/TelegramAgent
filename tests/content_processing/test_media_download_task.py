from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.content_processing.celery.tasks import media_download
from telegram_agent.core.content_processing.common.types import JobKind, JobStatus
from telegram_agent.core.content_processing.db.models.content_processing import Job
from telegram_agent.core.content_processing.db.repositories.sync_job import SyncSqlAlchemyJobRepository
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.services.sync_telegram_media_download import SyncTelegramMediaDownloadService


def test_duplicate_media_download_task_execution_claims_job_once(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_job(content_sync_sessionmaker)
    monkeypatch.setattr(
        media_download.SyncTelegramMediaDownloadService,
        "from_settings",
        classmethod(lambda cls: SyncTelegramMediaDownloadService(
            uow_factory=content_sync_uow_factory,
            settings=settings,
        )),
    )

    media_download.download_telegram_media_task.run(str(job_id))
    media_download.download_telegram_media_task.run(str(job_id))

    with content_sync_sessionmaker() as session:
        job = session.get(Job, job_id)

    assert job is not None
    assert job.status == JobStatus.FAILED


def test_job_state_claim_is_atomic(content_sync_sessionmaker: sessionmaker[Session]) -> None:
    job_id = _seed_job(content_sync_sessionmaker)

    with content_sync_sessionmaker() as session:
        repository = SyncSqlAlchemyJobRepository(session)
        claimed = repository.claim_for_download(job_id)
        session.commit()

    with content_sync_sessionmaker() as session:
        repository = SyncSqlAlchemyJobRepository(session)
        duplicate_claim = repository.claim_for_download(job_id)
        session.commit()

    assert claimed is not None
    assert claimed.status == JobStatus.RUNNING
    assert duplicate_claim is None


def _seed_job(content_sync_sessionmaker: sessionmaker[Session]):
    with content_sync_sessionmaker() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=JobStatus.QUEUED,
            idempotency_key=f"download-job-{uuid4()}",
            callback_required=True,
        )
        session.add(job)
        session.commit()
        return job.id
