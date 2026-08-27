"""SELECT-only queries against the content-processing database."""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.admin_dashboard.db.mappings import content_processing as tables
from telegram_agent.core.admin_dashboard.services.dubbing_status import dubbing_status_label
from telegram_agent.core.admin_dashboard.services.view_models import (
    DownloadRequestView,
    DubbingWorkflowRow,
    JobRow,
    MediaAssetRow,
    OutboxRow,
    TelegramSourceRow,
    TranscriptRow,
    TranscriptSegmentRow,
)


class ContentProcessingReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_source_by_ingress_message_id(
        self,
        ingress_message_id: UUID,
    ) -> TelegramSourceRow | None:
        tbl = tables.telegram_sources
        result = await self._session.execute(
            select(tbl).where(tbl.c.ingress_message_id == ingress_message_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return TelegramSourceRow(
            id=row.id,
            job_id=row.job_id,
            ingress_message_id=row.ingress_message_id,
            ingress_attachment_id=row.ingress_attachment_id,
            telegram_user_id=row.telegram_user_id,
            telegram_file_id=row.telegram_file_id,
            telegram_file_unique_id=row.telegram_file_unique_id,
            attachment_type=row.attachment_type,
        )

    async def get_job(self, job_id: UUID) -> JobRow | None:
        tbl = tables.jobs
        result = await self._session.execute(select(tbl).where(tbl.c.id == job_id))
        row = result.one_or_none()
        if row is None:
            return None
        return JobRow(
            id=row.id,
            kind=row.kind,
            status=row.status,
            idempotency_key=row.idempotency_key,
            error_message=row.error_message,
            callback_required=row.callback_required,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def list_assets(self, job_id: UUID) -> list[MediaAssetRow]:
        tbl = tables.media_assets
        result = await self._session.execute(
            select(tbl).where(tbl.c.job_id == job_id).order_by(tbl.c.role)
        )
        return [
            MediaAssetRow(
                id=row.id,
                job_id=row.job_id,
                role=row.role,
                parent_asset_id=row.parent_asset_id,
                local_path=row.local_path,
                media_type=row.media_type,
                mime_type=row.mime_type,
                duration_ms=row.duration_ms,
                size_bytes=row.size_bytes,
            )
            for row in result
        ]

    async def list_outbox(self, job_id: UUID) -> list[OutboxRow]:
        tbl = tables.outbox_events
        result = await self._session.execute(
            select(tbl)
            .where(tbl.c.job_id == job_id)
            .order_by(tbl.c.created_at.asc(), tbl.c.id.asc())
        )
        return [
            OutboxRow(
                id=row.id,
                event_type=row.event_type,
                status=row.status,
                attempt_count=row.attempt_count,
                created_at=row.created_at,
                published_at=row.published_at,
                available_at=row.available_at,
                locked_at=row.locked_at,
                locked_by=row.locked_by,
                last_error=row.last_error,
                idempotency_key=row.idempotency_key,
                payload=dict(row.payload or {}),
                job_id=row.job_id,
            )
            for row in result
        ]

    async def get_transcript(self, job_id: UUID) -> TranscriptRow | None:
        t = tables.transcripts
        s = tables.transcript_segments
        result = await self._session.execute(select(t).where(t.c.job_id == job_id))
        row = result.one_or_none()
        if row is None:
            return None
        seg_result = await self._session.execute(
            select(s)
            .where(s.c.transcript_id == row.id)
            .order_by(s.c.segment_index.asc())
        )
        segments = tuple(
            TranscriptSegmentRow(
                id=seg.id,
                transcript_id=seg.transcript_id,
                segment_index=seg.segment_index,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text=seg.text,
                language=seg.language,
                language_probability=seg.language_probability,
                speaker=seg.speaker,
                speaker_confidence=seg.speaker_confidence,
            )
            for seg in seg_result
        )
        return TranscriptRow(
            id=row.id,
            job_id=row.job_id,
            text=row.text,
            language=row.language,
            language_probability=row.language_probability,
            duration_ms=row.duration_ms,
            segments=segments,
        )

    async def list_job_status_by_ingress_ids(
        self,
        ingress_ids: list[UUID],
    ) -> dict[UUID, str]:
        if not ingress_ids:
            return {}
        src = tables.telegram_sources
        jobs = tables.jobs
        result = await self._session.execute(
            select(src.c.ingress_message_id, jobs.c.status)
            .select_from(src.join(jobs, jobs.c.id == src.c.job_id))
            .where(src.c.ingress_message_id.in_(ingress_ids))
        )
        return {row.ingress_message_id: row.status for row in result}

    async def list_download_requests_for_message(
        self,
        *,
        ingress_message_id: UUID,
        chat_id: int,
        telegram_message_id: int,
    ) -> list[DownloadRequestView]:
        requests = tables.download_requests
        jobs = tables.jobs
        workflows = tables.dubbing_workflows
        result = await self._session.execute(
            select(requests, jobs, workflows)
            .select_from(
                requests.outerjoin(jobs, jobs.c.id == requests.c.job_id).outerjoin(
                    workflows, workflows.c.job_id == requests.c.job_id
                )
            )
            .where(
                or_(
                    requests.c.media_ingress_message_id == ingress_message_id,
                    (requests.c.chat_id == chat_id)
                    & (requests.c.reply_to_message_id == telegram_message_id),
                )
            )
            .order_by(requests.c.created_at.desc(), requests.c.id.desc())
        )
        items: list[DownloadRequestView] = []
        seen: set[UUID] = set()
        for request, job_row, workflow_row in result:
            if request.id in seen:
                continue
            seen.add(request.id)
            items.append(
                DownloadRequestView(
                    id=request.id,
                    job_id=request.job_id,
                    media_ingress_message_id=request.media_ingress_message_id,
                    media_type=request.media_type,
                    requested_subtitle_language=request.requested_subtitle_language,
                    requested_dub_language=request.requested_dub_language,
                    delivery_status=request.delivery_status,
                    delivery_error=request.delivery_error,
                    assistant_text=request.assistant_text,
                    created_at=request.created_at,
                    updated_at=request.updated_at,
                    job=_job_row(job_row)
                    if job_row is not None and job_row.id is not None
                    else None,
                    dubbing=_dubbing_row(workflow_row)
                    if workflow_row is not None and workflow_row.id is not None
                    else None,
                )
            )
        return items


def _job_row(row: Any) -> JobRow:
    return JobRow(
        id=row.id,
        kind=row.kind,
        status=row.status,
        idempotency_key=row.idempotency_key,
        error_message=row.error_message,
        callback_required=row.callback_required,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _dubbing_row(row: Any) -> DubbingWorkflowRow:
    return DubbingWorkflowRow(
        id=row.id,
        job_id=row.job_id,
        source_job_id=row.source_job_id,
        target_language=row.target_language,
        status=row.status,
        status_label=dubbing_status_label(row.status),
        active_gpu_job_id=row.active_gpu_job_id,
        cosyvoice_model=row.cosyvoice_model,
        sam_model=row.sam_model,
        error_message=row.error_message,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )
