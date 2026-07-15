"""List recent ingress messages with optional secondary enrichment."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from uuid import UUID

from telegram_agent.core.admin_dashboard.common.settings import Settings
from telegram_agent.core.admin_dashboard.common.types import DbAvailability, DbName, OverallState
from telegram_agent.core.admin_dashboard.db.engines import DashboardDatabases
from telegram_agent.core.admin_dashboard.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard.db.readers.telegram_ingress import IngressReader
from telegram_agent.core.admin_dashboard.services.overall_state import (
    derive_overall_state,
    overall_state_label,
)
from telegram_agent.core.admin_dashboard.services.redact import text_preview
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    ContentProcessingView,
    JobRow,
    MessageListItem,
    MessageListResult,
    UserMessageRow,
)

logger = logging.getLogger(__name__)


class MessageListService:
    def __init__(self, databases: DashboardDatabases, settings: Settings) -> None:
        self._databases = databases
        self._settings = settings

    async def list_messages(
        self,
        *,
        page: int = 1,
        page_size: int | None = None,
        ingress_message_id: UUID | None = None,
        chat_id: int | None = None,
        message_id: int | None = None,
        telegram_user_id: int | None = None,
        conversation_status: str | None = None,
        attachment_status: str | None = None,
        has_attachment: bool | None = None,
        failed_only: bool = False,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        text_query: str | None = None,
    ) -> MessageListResult:
        size = page_size or self._settings.list_page_size
        size = max(1, min(size, self._settings.list_max_page_size))
        page = max(1, page)
        offset = (page - 1) * size

        secondary: dict[DbName, DbAvailability] = {
            DbName.CONTENT_PROCESSING: DbAvailability.SKIPPED,
            DbName.AGENT_RUNTIME: DbAvailability.SKIPPED,
        }

        filters = dict(
            ingress_message_id=ingress_message_id,
            chat_id=chat_id,
            message_id=message_id,
            telegram_user_id=telegram_user_id,
            conversation_status=conversation_status,
            attachment_status=attachment_status,
            has_attachment=has_attachment,
            failed_only=failed_only,
            created_from=created_from,
            created_to=created_to,
            text_query=text_query,
        )
        try:
            # AsyncSession does not allow concurrent operations on one session.
            # Run count + page sequentially on a single connection.
            async with self._databases.session(DbName.INGRESS) as session:
                reader = IngressReader(session)

                async def _load() -> tuple[int, list[UserMessageRow]]:
                    total_count = await reader.count_messages(**filters)
                    page_rows = await reader.list_messages(
                        limit=size,
                        offset=offset,
                        **filters,
                    )
                    return total_count, page_rows

                total, rows = await asyncio.wait_for(
                    _load(),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            ingress_availability = DbAvailability.OK
        except TimeoutError:
            logger.warning("Ingress list query timed out")
            return MessageListResult(
                items=(),
                total=0,
                page=page,
                page_size=size,
                ingress_availability=DbAvailability.TIMEOUT,
                secondary_availability=secondary,
            )
        except Exception:
            logger.exception("Ingress list query failed")
            return MessageListResult(
                items=(),
                total=0,
                page=page,
                page_size=size,
                ingress_availability=DbAvailability.ERROR,
                secondary_availability=secondary,
            )

        ids = [row.id for row in rows]
        job_statuses, job_availability = await self._job_statuses(ids)
        secondary[DbName.CONTENT_PROCESSING] = job_availability
        coord_statuses, coord_availability = await self._coord_statuses(ids)
        secondary[DbName.AGENT_RUNTIME] = coord_availability

        items = tuple(
            self._to_item(row, job_statuses.get(row.id), coord_statuses.get(row.id))
            for row in rows
        )
        return MessageListResult(
            items=items,
            total=total,
            page=page,
            page_size=size,
            ingress_availability=ingress_availability,
            secondary_availability=secondary,
        )

    def _to_item(
        self,
        row: UserMessageRow,
        job_status: str | None,
        coord_status: str | None,
    ) -> MessageListItem:
        content = None
        if job_status is not None:
            content = ContentProcessingView(
                job=JobRow(
                    id=row.id,
                    kind="telegram attachment",
                    status=job_status,
                    idempotency_key="",
                    error_message=None,
                    callback_required=True,
                    created_at=row.created_at,
                    updated_at=row.created_at,
                ),
                source=None,
            )
        runtime = None
        if coord_status is not None:
            from telegram_agent.core.admin_dashboard.services.view_models import RuntimeMessageRow

            runtime = AgentRuntimeView(
                message=RuntimeMessageRow(
                    id=row.id,
                    batch_id=row.id,
                    ingress_message_id=row.id,
                    chat_id=row.chat_id,
                    telegram_user_id=row.telegram_user_id,
                    message_id=row.message_id,
                    reply_message_id=row.reply_message_id,
                    text=row.text,
                    attachment_ingress_id=row.attachment.id if row.attachment else None,
                    attachment_type=row.attachment.type if row.attachment else None,
                    attachment_status=row.attachment.status if row.attachment else None,
                    attachment_file_id=None,
                    attachment_file_unique_id=None,
                    group_id=None,
                    coordination_status=coord_status,
                    coordinated_at=None,
                    created_at=row.created_at,
                ),
                batch=None,
                group=None,
                outbox=None,
                claim=None,
            )
        state = derive_overall_state(message=row, content=content, runtime=runtime)
        return MessageListItem(
            id=row.id,
            created_at=row.created_at,
            chat_id=row.chat_id,
            telegram_user_id=row.telegram_user_id,
            message_id=row.message_id,
            text_preview=text_preview(
                row.text,
                mask=self._settings.mask_message_text,
            ),
            conversation_status=row.conversation_status,
            has_attachment=row.attachment is not None,
            attachment_type=row.attachment.type if row.attachment else None,
            attachment_status=row.attachment.status if row.attachment else None,
            overall_state=state,
            overall_state_label=overall_state_label(state),
        )

    async def _job_statuses(
        self,
        ids: list[UUID],
    ) -> tuple[dict[UUID, str], DbAvailability]:
        if not ids:
            return {}, DbAvailability.SKIPPED
        try:
            async with self._databases.session(DbName.CONTENT_PROCESSING) as session:
                reader = ContentProcessingReader(session)
                data = await asyncio.wait_for(
                    reader.list_job_status_by_ingress_ids(ids),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return data, DbAvailability.OK
        except TimeoutError:
            return {}, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Content-processing enrichment failed")
            return {}, DbAvailability.ERROR

    async def _coord_statuses(
        self,
        ids: list[UUID],
    ) -> tuple[dict[UUID, str], DbAvailability]:
        if not ids:
            return {}, DbAvailability.SKIPPED
        try:
            async with self._databases.session(DbName.AGENT_RUNTIME) as session:
                reader = AgentRuntimeReader(session)
                data = await asyncio.wait_for(
                    reader.list_coordination_status_by_ingress_ids(ids),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return data, DbAvailability.OK
        except TimeoutError:
            return {}, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Agent-runtime enrichment failed")
            return {}, DbAvailability.ERROR
