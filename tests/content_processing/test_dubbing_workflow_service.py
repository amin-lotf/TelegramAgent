from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import GpuExecutionServiceError
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.common.utils import utcnow
from telegram_agent.core.content_processing.clients.gpu_execution_client import (
    GpuJobResponse,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    DownloadDeliveryStatus,
    DownloadMediaType,
    DubbingStatus,
    JobKind,
    JobStatus,
    MediaAssetRole,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    DownloadRequest,
    DubbingArtifact,
    DubbingWorkflow,
    Job,
    MediaAsset,
    OutboxEvent,
    TelegramSource,
    Transcript,
    TranscriptSegment,
)
from telegram_agent.core.content_processing.services.subtitle_preparation_service import (
    SubtitleSegment,
)
from telegram_agent.core.content_processing.services.sync_download_preparation_service import (
    SyncDownloadPreparationService,
)
from telegram_agent.core.content_processing.services.sync_dubbing_workflow_service import (
    SyncDubbingWorkflowService,
)


class _Translation:
    def ensure_translated(
        self,
        *,
        source_job_id: UUID,
        target_language: str | None,
        cancellation_requested=None,
    ) -> list[SubtitleSegment]:
        assert source_job_id
        text = "Hola mundo" if target_language == "es" else "Hello world"
        return [SubtitleSegment(start_ms=0, end_ms=1500, text=text)]


class _Clipper:
    def extract_clip(
        self,
        *,
        source_path: Path,
        start_ms: int,
        end_ms: int,
        dest_path: Path,
    ) -> Path:
        assert source_path.is_file()
        assert (start_ms, end_ms) == (0, 1500)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"prompt")
        return dest_path


class _Gpu:
    def __init__(self) -> None:
        self.workloads: dict[UUID, str] = {}
        self.submit_count = 0
        self.cancelled: list[UUID] = []

    def submit(self, *, workload_type: str, output_path: Path, **_kwargs) -> GpuJobResponse:
        self.submit_count += 1
        job_id = uuid4()
        self.workloads[job_id] = workload_type
        return GpuJobResponse(
            id=job_id,
            workload_type=workload_type,
            status="pending",
            output_path=str(output_path.resolve()),
        )

    def wait(
        self,
        *,
        job: GpuJobResponse,
        expected_output_path: Path,
        heartbeat,
        cancellation_requested=None,
    ) -> Path:
        assert cancellation_requested is not None
        heartbeat()
        expected_output_path.parent.mkdir(parents=True, exist_ok=True)
        if "cosyvoice" in self.workloads[job.id]:
            tts_dir = expected_output_path.parent / "tts"
            tts_dir.mkdir(parents=True, exist_ok=True)
            clip = tts_dir / "segment_00000.wav"
            clip.write_bytes(b"wav")
            manifest = tts_dir / "tts_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "segments": [
                            {
                                "index": 0,
                                "start_ms": 0,
                                "end_ms": 1500,
                                "tts_clip_path": str(clip),
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            payload = {"manifest_path": str(manifest)}
        else:
            sam_input = json.loads(
                (expected_output_path.parent / "sam_input.json").read_text(
                    encoding="utf-8"
                )
            )
            residual = Path(sam_input["residual_path"])
            residual.write_bytes(b"residual")
            payload = {"residual_path": str(residual)}
        expected_output_path.write_text(json.dumps(payload), encoding="utf-8")
        return expected_output_path

    def cancel(self, job_id: UUID) -> None:
        self.cancelled.append(job_id)


class _UnavailableCancelGpu(_Gpu):
    def cancel(self, job_id: UUID) -> None:
        self.cancelled.append(job_id)
        raise GpuExecutionServiceError("GPU service unavailable")


class _Assembly:
    def __init__(self, output: Path) -> None:
        self.output = output

    def assemble(self, **_kwargs) -> Path:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(b"mixed")
        return self.output


class _Subtitles:
    def __init__(self, output: Path) -> None:
        self.output = output

    def prepare(self, **_kwargs) -> str:
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text("1\n00:00:00,000 --> 00:00:01,500\nHola\n", encoding="utf-8")
        return str(self.output)


class _Mux:
    def __init__(self, output: Path) -> None:
        self.output = output

    def mux(self, **kwargs) -> str:
        assert kwargs["audio_language"] == "es"
        assert kwargs["subtitle_language"] == "en"
        assert kwargs["audio_bitrate"] == "192k"
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_bytes(b"dubbed-media")
        return str(self.output)


def test_dubbing_pipeline_persists_each_stage_and_final_delivery(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    source_job_id, ingress_message_id = _seed_source(
        content_sync_sessionmaker, tmp_path
    )
    download_job_id = _seed_download(
        content_sync_sessionmaker, ingress_message_id
    )
    service_settings = settings.model_copy(
        update={"media_storage_root": str(tmp_path), "subtitle_translation_enabled": True}
    )
    gpu = _Gpu()
    workflow = SyncDubbingWorkflowService(
        uow_factory=content_sync_uow_factory,
        settings=service_settings,
        translation_service=_Translation(),  # type: ignore[arg-type]
        gpu_client=gpu,  # type: ignore[arg-type]
        clipper=_Clipper(),  # type: ignore[arg-type]
        assembly_service=_Assembly(tmp_path / "mixed.wav"),  # type: ignore[arg-type]
        subtitle_service=_Subtitles(tmp_path / "subtitles.srt"),  # type: ignore[arg-type]
        mux_service=_Mux(tmp_path / "dubbed.mkv"),  # type: ignore[arg-type]
    )
    preparation = SyncDownloadPreparationService(
        uow_factory=content_sync_uow_factory,
        settings=service_settings,
        translation_service=_Translation(),  # type: ignore[arg-type]
        dubbing_service=workflow,
    )

    assert preparation.execute(job_id=download_job_id, retry_count=0).error_message is None
    for expected_status in (
        DubbingStatus.TTS_READY,
        DubbingStatus.SAM_READY,
        DubbingStatus.ASSEMBLY_READY,
        DubbingStatus.READY_FOR_DELIVERY,
    ):
        result = workflow.execute(job_id=download_job_id, retry_count=0)
        assert result.error_message is None
        with content_sync_sessionmaker() as session:
            persisted = session.scalar(
                select(DubbingWorkflow).where(
                    DubbingWorkflow.job_id == download_job_id
                )
            )
        assert persisted is not None and persisted.status == expected_status

    with content_sync_sessionmaker() as session:
        job = session.get(Job, download_job_id)
        request = session.scalar(
            select(DownloadRequest).where(DownloadRequest.job_id == download_job_id)
        )
        persisted = session.scalar(
            select(DubbingWorkflow).where(DubbingWorkflow.job_id == download_job_id)
        )
        artifacts = list(
            session.scalars(
                select(DubbingArtifact).where(
                    DubbingArtifact.workflow_id == persisted.id  # type: ignore[union-attr]
                )
            )
        )
        event_types = set(
            session.scalars(
                select(OutboxEvent.event_type).where(
                    OutboxEvent.job_id == download_job_id
                )
            )
        )
    assert source_job_id
    assert job is not None and job.status == JobStatus.COMPLETED
    assert request is not None
    assert request.final_path == str(tmp_path / "dubbed.mkv")
    assert request.delivery_status == DownloadDeliveryStatus.PENDING
    assert {item.artifact_type for item in artifacts} == {
        "dubbing_plan",
        "tts_manifest",
        "sam_input",
        "residual_audio",
        "mixed_audio",
        "subtitles",
        "final_media",
    }
    assert OutboxEventType.DOWNLOAD_READY_FOR_DELIVERY.value in event_types
    assert gpu.submit_count == 2


def test_duplicate_running_stage_waits_and_stale_stage_is_reclaimed(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    source_job_id, ingress_message_id = _seed_source(
        content_sync_sessionmaker, tmp_path
    )
    download_job_id = _seed_download(
        content_sync_sessionmaker, ingress_message_id
    )
    plan = tmp_path / str(download_job_id) / "dubbing" / "dubbing_plan.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text('{"segments": [{}]}', encoding="utf-8")
    with content_sync_sessionmaker() as session:
        workflow = DubbingWorkflow(
            job_id=download_job_id,
            source_job_id=source_job_id,
            target_language="es",
            status=DubbingStatus.TTS_RUNNING,
            cosyvoice_model=settings.cosyvoice_model,
            sam_model=settings.sam_audio_model,
        )
        session.add(workflow)
        session.flush()
        session.add(
            DubbingArtifact(
                workflow_id=workflow.id,
                artifact_type="dubbing_plan",
                local_path=str(plan),
                size_bytes=plan.stat().st_size,
            )
        )
        session.commit()
    gpu = _Gpu()
    service = SyncDubbingWorkflowService(
        uow_factory=content_sync_uow_factory,
        settings=settings.model_copy(
            update={
                "media_storage_root": str(tmp_path),
                "media_processing_lease_seconds": 60,
            }
        ),
        translation_service=_Translation(),  # type: ignore[arg-type]
        gpu_client=gpu,  # type: ignore[arg-type]
    )

    active = service.execute(job_id=download_job_id, retry_count=0)
    assert active.deferred is True
    assert gpu.submit_count == 0

    with content_sync_sessionmaker() as session:
        session.execute(
            update(DubbingWorkflow)
            .where(DubbingWorkflow.job_id == download_job_id)
            .values(updated_at=utcnow() - timedelta(minutes=2))
        )
        session.commit()
    recovered = service.execute(job_id=download_job_id, retry_count=1)
    assert recovered.error_message is None
    assert gpu.submit_count == 1
    with content_sync_sessionmaker() as session:
        persisted = session.scalar(
            select(DubbingWorkflow).where(DubbingWorkflow.job_id == download_job_id)
        )
    assert persisted is not None and persisted.status == DubbingStatus.SAM_READY


def test_cancellation_is_owned_by_request_user_and_persisted(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    source_job_id, ingress_message_id = _seed_source(
        content_sync_sessionmaker, tmp_path
    )
    download_job_id = _seed_download(
        content_sync_sessionmaker, ingress_message_id
    )
    gpu = _Gpu()
    service = SyncDubbingWorkflowService(
        uow_factory=content_sync_uow_factory,
        settings=settings.model_copy(update={"media_storage_root": str(tmp_path)}),
        translation_service=_Translation(),  # type: ignore[arg-type]
        gpu_client=gpu,  # type: ignore[arg-type]
    )
    service.start(
        job_id=download_job_id,
        source_job_id=source_job_id,
        target_language="es",
    )

    assert service.cancel(job_id=download_job_id, telegram_user_id=999) is False
    assert service.cancel(job_id=download_job_id, telegram_user_id=7) is True
    assert service.cancel(job_id=download_job_id, telegram_user_id=7) is True
    with content_sync_sessionmaker() as session:
        job = session.get(Job, download_job_id)
        workflow = session.scalar(
            select(DubbingWorkflow).where(DubbingWorkflow.job_id == download_job_id)
        )
        failures = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.job_id == download_job_id,
                    OutboxEvent.event_type
                    == OutboxEventType.DOWNLOAD_FAILED_FOR_DELIVERY.value,
                )
            )
        )
    assert job is not None and job.status == JobStatus.CANCELLED
    assert workflow is not None and workflow.status == DubbingStatus.CANCELLED
    assert len(failures) == 1


def test_timeout_cancellation_stops_active_gpu_job_before_delivery(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    source_job_id, ingress_message_id = _seed_source(
        content_sync_sessionmaker, tmp_path
    )
    download_job_id = _seed_download(
        content_sync_sessionmaker, ingress_message_id
    )
    gpu_job_id = uuid4()
    with content_sync_sessionmaker() as session:
        session.execute(
            update(Job)
            .where(Job.id == download_job_id)
            .values(status=JobStatus.TIMED_OUT)
        )
        session.add(
            DubbingWorkflow(
                job_id=download_job_id,
                source_job_id=source_job_id,
                target_language="es",
                status=DubbingStatus.CANCELLING,
                active_gpu_job_id=gpu_job_id,
                cosyvoice_model=settings.cosyvoice_model,
                sam_model=settings.sam_audio_model,
                cancellation_requested_at=utcnow(),
            )
        )
        session.commit()
    gpu = _Gpu()
    service = SyncDubbingWorkflowService(
        uow_factory=content_sync_uow_factory,
        settings=settings.model_copy(update={"media_storage_root": str(tmp_path)}),
        translation_service=_Translation(),  # type: ignore[arg-type]
        gpu_client=gpu,  # type: ignore[arg-type]
    )

    result = service.execute(job_id=download_job_id, retry_count=0)

    assert result.error_message is None
    assert gpu.cancelled == [gpu_job_id]
    with content_sync_sessionmaker() as session:
        job = session.get(Job, download_job_id)
        workflow = session.scalar(
            select(DubbingWorkflow).where(DubbingWorkflow.job_id == download_job_id)
        )
    assert job is not None and job.status == JobStatus.TIMED_OUT
    assert workflow is not None and workflow.status == DubbingStatus.CANCELLED


def test_gpu_cancel_outage_keeps_durable_cancelling_state(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    tmp_path: Path,
) -> None:
    source_job_id, ingress_message_id = _seed_source(
        content_sync_sessionmaker, tmp_path
    )
    download_job_id = _seed_download(
        content_sync_sessionmaker, ingress_message_id
    )
    gpu_job_id = uuid4()
    with content_sync_sessionmaker() as session:
        session.execute(
            update(Job)
            .where(Job.id == download_job_id)
            .values(status=JobStatus.CANCELLING)
        )
        session.add(
            DubbingWorkflow(
                job_id=download_job_id,
                source_job_id=source_job_id,
                target_language="es",
                status=DubbingStatus.CANCELLING,
                active_gpu_job_id=gpu_job_id,
                cosyvoice_model=settings.cosyvoice_model,
                sam_model=settings.sam_audio_model,
                cancellation_requested_at=utcnow(),
            )
        )
        session.commit()
    gpu = _UnavailableCancelGpu()
    service = SyncDubbingWorkflowService(
        uow_factory=content_sync_uow_factory,
        settings=settings.model_copy(update={"media_storage_root": str(tmp_path)}),
        translation_service=_Translation(),  # type: ignore[arg-type]
        gpu_client=gpu,  # type: ignore[arg-type]
    )

    result = service.execute(job_id=download_job_id, retry_count=99)

    assert result.deferred is True
    assert gpu.cancelled == [gpu_job_id]
    with content_sync_sessionmaker() as session:
        job = session.get(Job, download_job_id)
        workflow = session.scalar(
            select(DubbingWorkflow).where(
                DubbingWorkflow.job_id == download_job_id
            )
        )
    assert job is not None and job.status == JobStatus.CANCELLING
    assert workflow is not None and workflow.status == DubbingStatus.CANCELLING
    assert workflow.active_gpu_job_id == gpu_job_id


def _seed_source(
    sessionmaker_factory: sessionmaker[Session], root: Path
) -> tuple[UUID, UUID]:
    source_job_id = uuid4()
    ingress_message_id = uuid4()
    video = root / "source-video.mp4"
    audio = root / "source-audio.ogg"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=source_job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=JobStatus.COMPLETED,
                idempotency_key=f"source-{source_job_id}",
                callback_required=True,
            )
        )
        session.flush()
        session.add(
            TelegramSource(
                job_id=source_job_id,
                ingress_message_id=ingress_message_id,
                ingress_attachment_id=uuid4(),
                telegram_user_id=7,
                telegram_file_id="file",
                attachment_type=TelegramAttachmentType.VIDEO,
            )
        )
        source_asset_id = uuid4()
        session.add_all(
            [
                MediaAsset(
                    id=source_asset_id,
                    job_id=source_job_id,
                    role=MediaAssetRole.SOURCE,
                    local_path=str(video),
                    media_type=TelegramAttachmentType.VIDEO.value,
                    size_bytes=video.stat().st_size,
                ),
                MediaAsset(
                    job_id=source_job_id,
                    role=MediaAssetRole.VIDEO,
                    parent_asset_id=source_asset_id,
                    local_path=str(video),
                    media_type=TelegramAttachmentType.VIDEO.value,
                    size_bytes=video.stat().st_size,
                ),
                MediaAsset(
                    job_id=source_job_id,
                    role=MediaAssetRole.AUDIO,
                    parent_asset_id=source_asset_id,
                    local_path=str(audio),
                    media_type=TelegramAttachmentType.VIDEO.value,
                    size_bytes=audio.stat().st_size,
                ),
            ]
        )
        transcript = Transcript(
            job_id=source_job_id,
            text="Hello world",
            language="en",
            duration_ms=1500,
        )
        session.add(transcript)
        session.flush()
        session.add(
            TranscriptSegment(
                transcript_id=transcript.id,
                segment_index=0,
                start_ms=0,
                end_ms=1500,
                text="Hello world",
                language="en",
            )
        )
        session.commit()
    return source_job_id, ingress_message_id


def _seed_download(
    sessionmaker_factory: sessionmaker[Session], ingress_message_id: UUID
) -> UUID:
    job_id = uuid4()
    with sessionmaker_factory() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.DOWNLOAD_PREPARATION,
                status=JobStatus.QUEUED,
                idempotency_key=f"download-{job_id}",
                callback_required=False,
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
                media_ingress_message_id=ingress_message_id,
                media_type=DownloadMediaType.VIDEO.value,
                requested_subtitle_language="en",
                requested_dub_language="es",
                assistant_text="Here is your dub",
            )
        )
        session.commit()
    return job_id
