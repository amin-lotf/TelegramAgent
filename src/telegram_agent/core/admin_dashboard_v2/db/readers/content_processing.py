from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.db.tables.content_processing import (
    jobs,
    media_assets,
    outbox_events,
    telegram_sources,
    transcript_segments,
    transcripts,
)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


class ContentProcessingReader:
    source = "content_processing"

    def __init__(self, databases: ReadDatabaseManager) -> None:
        self._databases = databases

    async def statuses_by_ingress_ids(
        self,
        ingress_message_ids: Collection[UUID],
        *,
        attempt_limit: int,
    ) -> dict[UUID, tuple[dict[str, Any], ...]]:
        if not ingress_message_ids:
            return {}
        ranked_attempts = (
            select(
                telegram_sources.c.ingress_message_id,
                telegram_sources.c.ingress_attachment_id,
                telegram_sources.c.attachment_type,
                jobs.c.id.label("job_id"),
                jobs.c.status,
                jobs.c.error_message,
                jobs.c.idempotency_key,
                jobs.c.created_at,
                jobs.c.updated_at,
                func.row_number()
                .over(
                    partition_by=telegram_sources.c.ingress_message_id,
                    order_by=(jobs.c.created_at.desc(), jobs.c.id.desc()),
                )
                .label("attempt_rank"),
            )
            .join(jobs, jobs.c.id == telegram_sources.c.job_id)
            .where(telegram_sources.c.ingress_message_id.in_(ingress_message_ids))
            .subquery()
        )
        statement = (
            select(ranked_attempts)
            .where(ranked_attempts.c.attempt_rank <= attempt_limit)
            .order_by(
                ranked_attempts.c.ingress_message_id,
                ranked_attempts.c.created_at,
                ranked_attempts.c.job_id,
            )
        )
        async with self._databases.connection(self.source) as connection:
            rows = (await connection.execute(statement)).all()
        grouped: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            item = _mapping(row)
            item.pop("attempt_rank")
            grouped[item.pop("ingress_message_id")].append(item)
        return {key: tuple(value) for key, value in grouped.items()}

    async def resolve_ingress_ids_by_job_id(self, job_id: UUID) -> set[UUID]:
        async with self._databases.connection(self.source) as connection:
            values = (
                await connection.execute(
                    select(telegram_sources.c.ingress_message_id).where(
                        telegram_sources.c.job_id == job_id
                    )
                )
            ).scalars()
            return set(values)

    async def get_trace(
        self,
        ingress_message_id: UUID,
        *,
        attempt_limit: int,
        asset_limit: int,
        outbox_limit: int,
        segment_limit: int,
    ) -> dict[str, Any] | None:
        source_job_statement = (
            select(
                telegram_sources.c.id.label("source_id"),
                telegram_sources.c.job_id,
                telegram_sources.c.ingress_message_id,
                telegram_sources.c.ingress_attachment_id,
                telegram_sources.c.telegram_user_id,
                telegram_sources.c.telegram_file_id,
                telegram_sources.c.telegram_file_unique_id,
                telegram_sources.c.attachment_type,
                jobs.c.kind,
                jobs.c.status,
                jobs.c.idempotency_key,
                jobs.c.error_message,
                jobs.c.callback_required,
                jobs.c.created_at,
                jobs.c.updated_at,
            )
            .join(jobs, jobs.c.id == telegram_sources.c.job_id)
            .where(telegram_sources.c.ingress_message_id == ingress_message_id)
            .order_by(jobs.c.created_at.desc(), jobs.c.id.desc())
            .limit(attempt_limit + 1)
        )
        async with self._databases.connection(self.source) as connection:
            source_rows = (await connection.execute(source_job_statement)).all()
            if not source_rows:
                return None
            attempts_truncated = len(source_rows) > attempt_limit
            attempts = [_mapping(row) for row in source_rows[:attempt_limit]]
            attempts.reverse()
            job_ids = [attempt["job_id"] for attempt in attempts]
            asset_rows = (
                await connection.execute(
                    select(media_assets)
                    .where(media_assets.c.job_id.in_(job_ids))
                    .order_by(media_assets.c.job_id, media_assets.c.role, media_assets.c.id)
                    .limit(asset_limit + 1)
                )
            ).all()
            assets_truncated = len(asset_rows) > asset_limit
            asset_rows = asset_rows[:asset_limit]
            event_rows = (
                await connection.execute(
                    select(outbox_events)
                    .where(outbox_events.c.job_id.in_(job_ids))
                    .order_by(outbox_events.c.created_at.desc(), outbox_events.c.id.desc())
                    .limit(outbox_limit + 1)
                )
            ).all()
            events_truncated = len(event_rows) > outbox_limit
            event_rows = list(reversed(event_rows[:outbox_limit]))
            transcript_rows = (
                await connection.execute(
                    select(transcripts).where(transcripts.c.job_id.in_(job_ids))
                )
            ).all()
            transcript_items = [_mapping(row) for row in transcript_rows]
            transcript_ids = [item["id"] for item in transcript_items]
            segment_rows = []
            if transcript_ids:
                segment_rows = (
                    await connection.execute(
                        select(transcript_segments)
                        .where(transcript_segments.c.transcript_id.in_(transcript_ids))
                        .order_by(
                            transcript_segments.c.transcript_id,
                            transcript_segments.c.segment_index,
                        )
                        .limit(segment_limit + 1)
                    )
                ).all()
            segments_truncated = len(segment_rows) > segment_limit
            segment_rows = segment_rows[:segment_limit]

        assets_by_job: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in asset_rows:
            item = _mapping(row)
            assets_by_job[item["job_id"]].append(item)
        events_by_job: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in event_rows:
            item = _mapping(row)
            events_by_job[item["job_id"]].append(item)
        transcripts_by_job = {item["job_id"]: item for item in transcript_items}
        segments_by_transcript: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
        for row in segment_rows:
            item = _mapping(row)
            segments_by_transcript[item["transcript_id"]].append(item)

        for attempt in attempts:
            job_id = attempt["job_id"]
            attempt["assets"] = assets_by_job.get(job_id, [])
            attempt["outbox_events"] = events_by_job.get(job_id, [])
            transcript = transcripts_by_job.get(job_id)
            if transcript is not None:
                transcript["segments"] = segments_by_transcript.get(transcript["id"], [])
            attempt["transcript"] = transcript
        return {
            "attempts": attempts,
            "attempts_truncated": attempts_truncated,
            "media_assets_truncated": assets_truncated,
            "outbox_events_truncated": events_truncated,
            "transcript_segments_truncated": segments_truncated,
        }
