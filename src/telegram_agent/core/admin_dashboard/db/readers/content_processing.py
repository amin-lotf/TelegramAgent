"""SELECT-only queries against the content-processing database."""
from __future__ import annotations

from dataclasses import replace
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
    SubtitleTranslationRow,
    TelegramSourceRow,
    TranslationBatchRow,
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
        agent_message_ids: tuple[UUID, ...] = (),
        creator_by_agent_message_id: dict[UUID, UUID] | None = None,
        include_media_match: bool = True,
        include_reply_fallback: bool = True,
        enrich: bool = True,
    ) -> list[DownloadRequestView]:
        requests = tables.download_requests
        jobs = tables.jobs
        workflows = tables.dubbing_workflows
        conditions = []
        if agent_message_ids:
            conditions.append(requests.c.agent_message_id.in_(agent_message_ids))
        if include_media_match:
            conditions.append(requests.c.media_ingress_message_id == ingress_message_id)
        if include_reply_fallback:
            conditions.append(
                (requests.c.chat_id == chat_id)
                & (requests.c.reply_to_message_id == telegram_message_id)
            )
        if not conditions:
            return []
        result = await self._session.execute(
            select(
                requests.c.id.label("request_id"),
                requests.c.job_id.label("request_job_id"),
                requests.c.group_id.label("request_group_id"),
                requests.c.agent_message_id.label("request_agent_message_id"),
                requests.c.media_ingress_message_id,
                requests.c.media_type,
                requests.c.requested_subtitle_language,
                requests.c.requested_dub_language,
                requests.c.requested_language,
                requests.c.requested_format,
                requests.c.assistant_text,
                requests.c.reply_to_message_id,
                requests.c.final_path,
                requests.c.delivery_status,
                requests.c.delivery_attempt_count,
                requests.c.delivery_error,
                requests.c.delivered_at,
                requests.c.created_at.label("request_created_at"),
                requests.c.updated_at.label("request_updated_at"),
                jobs.c.id.label("joined_job_id"),
                jobs.c.kind.label("job_kind"),
                jobs.c.status.label("job_status"),
                jobs.c.idempotency_key.label("job_idempotency_key"),
                jobs.c.error_message.label("job_error_message"),
                jobs.c.callback_required.label("job_callback_required"),
                jobs.c.created_at.label("job_created_at"),
                jobs.c.updated_at.label("job_updated_at"),
                workflows.c.id.label("workflow_id"),
                workflows.c.job_id.label("workflow_job_id"),
                workflows.c.source_job_id.label("workflow_source_job_id"),
                workflows.c.target_language.label("workflow_target_language"),
                workflows.c.status.label("workflow_status"),
                workflows.c.active_gpu_job_id.label("workflow_active_gpu_job_id"),
                workflows.c.cosyvoice_model.label("workflow_cosyvoice_model"),
                workflows.c.sam_model.label("workflow_sam_model"),
                workflows.c.error_message.label("workflow_error_message"),
                workflows.c.created_at.label("workflow_created_at"),
                workflows.c.updated_at.label("workflow_updated_at"),
            )
            .select_from(
                requests.outerjoin(jobs, jobs.c.id == requests.c.job_id).outerjoin(
                    workflows, workflows.c.job_id == requests.c.job_id
                )
            )
            .where(or_(*conditions))
            .order_by(requests.c.created_at.desc(), requests.c.id.desc())
        )
        items: list[DownloadRequestView] = []
        seen: set[UUID] = set()
        for row in result.mappings():
            request_id = row["request_id"]
            if request_id in seen:
                continue
            seen.add(request_id)
            job = None
            if row["joined_job_id"] is not None:
                job = JobRow(
                    id=row["joined_job_id"],
                    kind=row["job_kind"],
                    status=row["job_status"],
                    idempotency_key=row["job_idempotency_key"],
                    error_message=row["job_error_message"],
                    callback_required=row["job_callback_required"],
                    created_at=row["job_created_at"],
                    updated_at=row["job_updated_at"],
                )
            workflow = None
            if row["workflow_id"] is not None:
                workflow_status = row["workflow_status"]
                workflow = DubbingWorkflowRow(
                    id=row["workflow_id"],
                    job_id=row["workflow_job_id"],
                    source_job_id=row["workflow_source_job_id"],
                    target_language=row["workflow_target_language"],
                    status=workflow_status,
                    status_label=dubbing_status_label(workflow_status),
                    active_gpu_job_id=row["workflow_active_gpu_job_id"],
                    cosyvoice_model=row["workflow_cosyvoice_model"],
                    sam_model=row["workflow_sam_model"],
                    error_message=row["workflow_error_message"],
                    created_at=row["workflow_created_at"],
                    updated_at=row["workflow_updated_at"],
                )
            items.append(
                DownloadRequestView(
                    id=request_id,
                    job_id=row["request_job_id"],
                    media_ingress_message_id=row["media_ingress_message_id"],
                    media_type=row["media_type"],
                    requested_subtitle_language=row["requested_subtitle_language"],
                    requested_dub_language=row["requested_dub_language"],
                    requested_language=row["requested_language"],
                    requested_format=row["requested_format"],
                    delivery_status=row["delivery_status"],
                    delivery_attempt_count=row["delivery_attempt_count"],
                    delivery_error=row["delivery_error"],
                    delivered_at=row["delivered_at"],
                    assistant_text=row["assistant_text"],
                    created_at=row["request_created_at"],
                    updated_at=row["request_updated_at"],
                    group_id=row["request_group_id"],
                    agent_message_id=row["request_agent_message_id"],
                    reply_to_message_id=row["reply_to_message_id"],
                    final_path_exists=bool(row["final_path"]),
                    creator_ingress_message_id=(
                        (creator_by_agent_message_id or {}).get(
                            row["request_agent_message_id"]
                        )
                    ),
                    job=job,
                    dubbing=workflow,
                )
            )
        if enrich:
            enriched: list[DownloadRequestView] = []
            for item in items:
                enriched.append(await self._enrich_download_request(item))
            return enriched
        return items

    async def list_download_requests_by_agent_message_ids(
        self,
        agent_message_ids: list[UUID],
        *,
        creator_by_agent_message_id: dict[UUID, UUID],
    ) -> list[DownloadRequestView]:
        if not agent_message_ids:
            return []
        # Placeholder identity values are not used because both fallback predicates
        # are disabled; the shared loader still provides stable row conversion.
        rows = await self.list_download_requests_for_message(
            ingress_message_id=UUID(int=0),
            chat_id=0,
            telegram_message_id=0,
            agent_message_ids=tuple(agent_message_ids),
            creator_by_agent_message_id=creator_by_agent_message_id,
            include_media_match=False,
            include_reply_fallback=False,
            enrich=False,
        )
        return await self._enrich_download_requests_batch(rows)

    async def _enrich_download_requests_batch(
        self,
        requests: list[DownloadRequestView],
    ) -> list[DownloadRequestView]:
        if not requests:
            return []
        media_ids = {item.media_ingress_message_id for item in requests}
        sources = tables.telegram_sources
        jobs = tables.jobs
        transcripts = tables.transcripts
        source_result = await self._session.execute(
            select(
                sources.c.ingress_message_id,
                jobs,
                transcripts.c.language.label("transcript_language"),
            )
            .select_from(
                sources.join(jobs, jobs.c.id == sources.c.job_id).outerjoin(
                    transcripts, transcripts.c.job_id == sources.c.job_id
                )
            )
            .where(sources.c.ingress_message_id.in_(media_ids))
            .order_by(sources.c.ingress_message_id, jobs.c.created_at.desc())
        )
        source_by_ingress: dict[UUID, tuple[JobRow, str | None]] = {}
        for row in source_result:
            ingress_id = row.ingress_message_id
            if ingress_id not in source_by_ingress:
                source_by_ingress[ingress_id] = (
                    _job_row(row),
                    row.transcript_language,
                )

        source_job_ids = {item[0].id for item in source_by_ingress.values()}
        translations_by_key: dict[tuple[UUID, str], SubtitleTranslationRow] = {}
        if source_job_ids:
            translations = tables.subtitle_translations
            translation_result = await self._session.execute(
                select(translations).where(translations.c.job_id.in_(source_job_ids))
            )
            for row in translation_result:
                translations_by_key[(row.job_id, row.target_language.casefold())] = (
                    SubtitleTranslationRow(
                        id=row.id,
                        job_id=row.job_id,
                        source_language=row.source_language,
                        target_language=row.target_language,
                        status=row.status,
                        model_name=row.model_name,
                        error_message=row.error_message,
                        created_at=row.created_at,
                        updated_at=row.updated_at,
                        completed_at=row.completed_at,
                    )
                )

        enriched: list[DownloadRequestView] = []
        for request in requests:
            source = source_by_ingress.get(request.media_ingress_message_id)
            source_job = source[0] if source is not None else None
            source_language = source[1] if source is not None else None
            target = request.requested_dub_language or request.requested_subtitle_language
            translation = None
            if source_job is not None and target:
                translation = translations_by_key.get(
                    (source_job.id, target.strip().casefold())
                )
            enriched.append(
                replace(
                    request,
                    source_job=source_job,
                    source_transcript_language=source_language,
                    translation=translation,
                )
            )
        return enriched

    async def _enrich_download_request(
        self,
        request: DownloadRequestView,
    ) -> DownloadRequestView:
        source = await self.get_source_by_ingress_message_id(
            request.media_ingress_message_id
        )
        source_job = await self.get_job(source.job_id) if source is not None else None
        source_transcript = (
            await self.get_transcript(source.job_id) if source is not None else None
        )
        target_language = (
            request.requested_dub_language or request.requested_subtitle_language
        )
        translation = None
        if source is not None and target_language:
            translation = await self.get_translation(
                job_id=source.job_id,
                target_language=target_language,
            )
        return replace(
            request,
            source_job=source_job,
            source_transcript_language=(
                source_transcript.language if source_transcript is not None else None
            ),
            translation=translation,
            outbox_events=tuple(await self.list_outbox(request.job_id)),
        )

    async def get_translation(
        self,
        *,
        job_id: UUID,
        target_language: str,
    ) -> SubtitleTranslationRow | None:
        translations = tables.subtitle_translations
        result = await self._session.execute(
            select(translations).where(
                translations.c.job_id == job_id,
                translations.c.target_language == target_language.strip().casefold(),
            )
        )
        row = result.one_or_none()
        if row is None:
            # Historical rows may preserve the requested spelling/case.
            result = await self._session.execute(
                select(translations).where(
                    translations.c.job_id == job_id,
                    translations.c.target_language.ilike(target_language.strip()),
                )
            )
            row = result.one_or_none()
        if row is None:
            return None
        batches = tables.translation_batches
        batch_result = await self._session.execute(
            select(batches)
            .where(batches.c.subtitle_translation_id == row.id)
            .order_by(batches.c.batch_index.asc())
        )
        return SubtitleTranslationRow(
            id=row.id,
            job_id=row.job_id,
            source_language=row.source_language,
            target_language=row.target_language,
            status=row.status,
            model_name=row.model_name,
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            completed_at=row.completed_at,
            batches=tuple(
                TranslationBatchRow(
                    id=batch.id,
                    batch_index=batch.batch_index,
                    start_segment_index=batch.start_segment_index,
                    end_segment_index=batch.end_segment_index,
                    status=batch.status,
                    attempt_count=batch.attempt_count,
                    last_error=batch.last_error,
                    created_at=batch.created_at,
                    updated_at=batch.updated_at,
                )
                for batch in batch_result
            ),
        )


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
