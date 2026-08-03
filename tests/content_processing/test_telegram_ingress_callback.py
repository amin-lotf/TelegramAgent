from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.types import (
    AttachmentProcessingResultStatus,
    TelegramAttachmentType,
)
from telegram_agent.core.content_processing.common.types import JobKind, JobStatus
from telegram_agent.core.content_processing.db.models.content_processing import (
    Job,
    TelegramSource,
    Transcript,
)
from telegram_agent.core.content_processing.services.sync_telegram_ingress_callback import (
    SyncTelegramIngressCallbackService,
)


class StubTelegramIngressClient:
    def __init__(self) -> None:
        self.commands = []

    def notify_processing_result(self, command) -> None:
        self.commands.append(command)


@pytest.mark.parametrize(
    ("job_status", "with_transcript", "expected_status", "expected_text"),
    [
        (
            JobStatus.COMPLETED,
            True,
            AttachmentProcessingResultStatus.COMPLETED,
            "hello from voice",
        ),
        (
            JobStatus.EMOTION_EXTRACTED,
            True,
            AttachmentProcessingResultStatus.COMPLETED,
            "hello from voice",
        ),
        (
            JobStatus.TRANSCRIBED,
            True,
            AttachmentProcessingResultStatus.COMPLETED,
            "hello from voice",
        ),
        (
            JobStatus.CHUNKED,
            True,
            AttachmentProcessingResultStatus.COMPLETED,
            "hello from voice",
        ),
        (
            JobStatus.FAILED,
            False,
            AttachmentProcessingResultStatus.FAILED,
            None,
        ),
        (
            JobStatus.TIMED_OUT,
            False,
            AttachmentProcessingResultStatus.TIMED_OUT,
            None,
        ),
    ],
)
def test_callback_service_builds_terminal_ingress_request(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    job_status: JobStatus,
    with_transcript: bool,
    expected_status: AttachmentProcessingResultStatus,
    expected_text: str | None,
) -> None:
    job_id, message_id, attachment_id = _seed_terminal_job(
        content_sync_sessionmaker,
        status=job_status,
        with_transcript=with_transcript,
    )
    client = StubTelegramIngressClient()

    SyncTelegramIngressCallbackService(
        uow_factory=content_sync_uow_factory,
        client=client,
    ).execute(job_id)

    assert len(client.commands) == 1
    command = client.commands[0]
    assert command.ingress_message_id == message_id
    assert command.ingress_attachment_id == attachment_id
    assert command.status == expected_status
    assert command.transcribed_text == expected_text


def test_callback_service_skips_jobs_that_do_not_require_callback(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id, _, _ = _seed_terminal_job(
        content_sync_sessionmaker,
        status=JobStatus.COMPLETED,
        with_transcript=True,
        callback_required=False,
    )
    client = StubTelegramIngressClient()

    SyncTelegramIngressCallbackService(
        uow_factory=content_sync_uow_factory,
        client=client,
    ).execute(job_id)

    assert client.commands == []


def _seed_terminal_job(
    sessionmaker_: sessionmaker[Session],
    *,
    status: JobStatus,
    with_transcript: bool,
    callback_required: bool = True,
):
    with sessionmaker_() as session:
        job = Job(
            kind=JobKind.TELEGRAM_ATTACHMENT,
            status=status,
            idempotency_key=f"callback-{uuid4()}",
            callback_required=callback_required,
        )
        session.add(job)
        session.flush()

        message_id = uuid4()
        attachment_id = uuid4()
        session.add(
            TelegramSource(
                job_id=job.id,
                ingress_message_id=message_id,
                ingress_attachment_id=attachment_id,
                telegram_user_id=1,
                telegram_file_id="file-id",
                telegram_file_unique_id=None,
                attachment_type=TelegramAttachmentType.VOICE,
            )
        )
        if with_transcript:
            session.add(
                Transcript(
                    job_id=job.id,
                    text="hello from voice",
                    language="en",
                    language_probability=0.99,
                    duration_ms=1000,
                )
            )
        session.commit()
        return job.id, message_id, attachment_id
