from __future__ import annotations

from collections.abc import Collection
from typing import Any, cast
from uuid import UUID

from telegram_agent.core.admin_dashboard_v2.common.exceptions import (
    DataSourceUnavailableError,
    FilterUnavailableError,
)
from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.common.types import (
    CursorPosition,
    DataSourceStatus,
    MessageListFilters,
    MessagePageView,
    MessageSummaryView,
    SourceResult,
)
from telegram_agent.core.admin_dashboard_v2.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard_v2.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_auth import TelegramAuthReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_ingress import TelegramIngressReader
from telegram_agent.core.admin_dashboard_v2.services.cursors import CursorCodec


_PENDING_INGRESS = {"pending", "enqueued"}
_PENDING_CONTENT = {"queued", "running", "downloaded", "transcribing"}


class MessageListingService:
    def __init__(
        self,
        *,
        ingress: TelegramIngressReader,
        content: ContentProcessingReader,
        runtime: AgentRuntimeReader,
        auth: TelegramAuthReader,
        settings: Settings,
    ) -> None:
        self._ingress = ingress
        self._content = content
        self._runtime = runtime
        self._auth = auth
        self._settings = settings
        self._cursor_codec = CursorCodec(settings.cursor_secret.get_secret_value())

    async def list_messages(
        self,
        *,
        filters: MessageListFilters,
        cursor_value: str | None,
        page_size: int,
    ) -> MessagePageView:
        page_size = min(max(page_size, 1), self._settings.maximum_page_size)
        cursor = self._cursor_codec.decode(cursor_value, filters) if cursor_value else None
        allowed_ids = await self._resolve_exact_cross_service_ids(filters)
        items: list[MessageSummaryView] = []
        scanned_count = 0
        source_states: dict[str, SourceResult[None]] = {}
        last_position: CursorPosition | None = None
        last_chunk_full = False

        while len(items) < page_size and scanned_count < self._settings.listing_scan_limit:
            remaining_scan = self._settings.listing_scan_limit - scanned_count
            chunk_limit = min(self._settings.listing_chunk_size, remaining_scan)
            try:
                rows = await self._ingress.list_messages(
                    filters=filters,
                    cursor=cursor,
                    limit=chunk_limit,
                    allowed_ingress_ids=allowed_ids,
                )
            except DataSourceUnavailableError as exc:
                return MessagePageView(
                    items=(),
                    next_cursor=None,
                    scanned_count=0,
                    scan_limit_reached=False,
                    source_states=(
                        SourceResult(
                            source=exc.source,
                            status=DataSourceStatus.UNAVAILABLE,
                            message=exc.reason,
                        ),
                    ),
                )
            if not rows:
                last_chunk_full = False
                break
            last_chunk_full = len(rows) == chunk_limit
            ingress_ids = [row["id"] for row in rows]
            user_ids = [row["telegram_user_id"] for row in rows]

            content_by_id: dict[UUID, tuple[dict[str, object], ...]] = {}
            runtime_by_id: dict[UUID, dict[str, object]] = {}
            auth_by_id: dict[int, dict[str, object]] = {}
            content_available = True
            runtime_available = True

            try:
                content_by_id = await self._content.statuses_by_ingress_ids(
                    ingress_ids,
                    attempt_limit=self._settings.maximum_content_attempts,
                )
                source_states[self._content.source] = SourceResult(
                    source=self._content.source, status=DataSourceStatus.AVAILABLE
                )
            except DataSourceUnavailableError as exc:
                content_available = False
                source_states[exc.source] = SourceResult(
                    source=exc.source,
                    status=DataSourceStatus.UNAVAILABLE,
                    message=exc.reason,
                )
                if filters.content_status or filters.failed_only:
                    raise FilterUnavailableError(exc.source) from exc
            try:
                runtime_by_id = await self._runtime.statuses_by_ingress_ids(ingress_ids)
                source_states[self._runtime.source] = SourceResult(
                    source=self._runtime.source, status=DataSourceStatus.AVAILABLE
                )
            except DataSourceUnavailableError as exc:
                runtime_available = False
                source_states[exc.source] = SourceResult(
                    source=exc.source,
                    status=DataSourceStatus.UNAVAILABLE,
                    message=exc.reason,
                )
                if filters.runtime_status or filters.failed_only:
                    raise FilterUnavailableError(exc.source) from exc
            try:
                auth_by_id = await self._auth.users_by_telegram_ids(user_ids)
                source_states[self._auth.source] = SourceResult(
                    source=self._auth.source, status=DataSourceStatus.AVAILABLE
                )
            except DataSourceUnavailableError as exc:
                source_states[exc.source] = SourceResult(
                    source=exc.source,
                    status=DataSourceStatus.UNAVAILABLE,
                    message=exc.reason,
                )

            for row in rows:
                scanned_count += 1
                last_position = CursorPosition(row["created_at"], row["id"])
                content_attempts = content_by_id.get(row["id"], ())
                runtime_item = runtime_by_id.get(row["id"])
                if not self._matches_cross_filters(
                    row=row,
                    content_attempts=content_attempts,
                    runtime_item=runtime_item,
                    filters=filters,
                ):
                    continue
                user = auth_by_id.get(row["telegram_user_id"])
                items.append(
                    self._to_summary(
                        row,
                        content_attempts=content_attempts,
                        runtime_item=runtime_item,
                        user=user,
                        partial=not content_available or not runtime_available,
                    )
                )
                if len(items) >= page_size:
                    break
            cursor = last_position

        has_more = last_position is not None and (
            len(items) >= page_size or last_chunk_full or scanned_count >= self._settings.listing_scan_limit
        )
        next_cursor = (
            self._cursor_codec.encode(last_position, filters)
            if has_more and last_position is not None
            else None
        )
        return MessagePageView(
            items=tuple(items),
            next_cursor=next_cursor,
            scanned_count=scanned_count,
            scan_limit_reached=scanned_count >= self._settings.listing_scan_limit,
            source_states=tuple(source_states.values()),
        )

    async def _resolve_exact_cross_service_ids(
        self, filters: MessageListFilters
    ) -> Collection[UUID] | None:
        sets: list[set[UUID]] = []
        if filters.content_job_id is not None:
            try:
                sets.append(await self._content.resolve_ingress_ids_by_job_id(filters.content_job_id))
            except DataSourceUnavailableError as exc:
                raise FilterUnavailableError(exc.source) from exc
        if filters.runtime_group_id is not None:
            try:
                sets.append(await self._runtime.resolve_ingress_ids_by_group_id(filters.runtime_group_id))
            except DataSourceUnavailableError as exc:
                raise FilterUnavailableError(exc.source) from exc
        if not sets:
            return None
        result = sets[0]
        for values in sets[1:]:
            result &= values
        return result

    @staticmethod
    def _matches_cross_filters(
        *,
        row: dict[str, object],
        content_attempts: tuple[dict[str, object], ...],
        runtime_item: dict[str, object] | None,
        filters: MessageListFilters,
    ) -> bool:
        if filters.content_status and not any(
            attempt["status"] == filters.content_status for attempt in content_attempts
        ):
            return False
        if filters.runtime_status and (
            runtime_item is None
            or runtime_item["coordination_status"] != filters.runtime_status
        ):
            return False
        if filters.failed_only:
            failed = (
                row["conversation_status"] == "failed"
                or row.get("attachment_status") == "failed"
                or any(attempt["status"] == "failed" for attempt in content_attempts)
                or (
                    runtime_item is not None
                    and runtime_item.get("outbox_status") == "failed"
                )
            )
            if not failed:
                return False
        return True

    @staticmethod
    def _to_summary(
        row: dict[str, object],
        *,
        content_attempts: tuple[dict[str, object], ...],
        runtime_item: dict[str, object] | None,
        user: dict[str, object] | None,
        partial: bool,
    ) -> MessageSummaryView:
        content_statuses = tuple(str(item["status"]) for item in content_attempts)
        runtime_status = str(runtime_item["coordination_status"]) if runtime_item else None
        has_failure = (
            row["conversation_status"] == "failed"
            or row.get("attachment_status") == "failed"
            or "failed" in content_statuses
            or (runtime_item is not None and runtime_item.get("outbox_status") == "failed")
        )
        has_pending = (
            row["conversation_status"] in _PENDING_INGRESS
            or row.get("attachment_status") in {"pending", "processing"}
            or any(status in _PENDING_CONTENT for status in content_statuses)
            or runtime_status == "pending"
        )
        if has_failure:
            overall = "failed"
        elif has_pending:
            overall = "pending"
        elif runtime_status in {"grouped", "vague"}:
            overall = "coordinated"
        elif row["conversation_status"] == "dispatched":
            overall = "dispatched"
        else:
            overall = str(row["conversation_status"])
        text = str(row.get("text") or "")
        preview = text[:117] + "…" if len(text) > 120 else text
        if not preview and row.get("attachment_type"):
            preview = f"[{row['attachment_type']} attachment]"
        label = None
        if user:
            name = " ".join(
                str(value) for value in (user.get("first_name"), user.get("last_name")) if value
            ).strip()
            label = name or (f"@{user['username']}" if user.get("username") else None)
        return MessageSummaryView(
            ingress_message_id=row["id"],  # type: ignore[arg-type]
            telegram_user_id=int(cast(Any, row["telegram_user_id"])),
            chat_id=int(cast(Any, row["chat_id"])),
            message_id=int(cast(Any, row["message_id"])),
            update_id=int(cast(Any, row["update_id"])) if row.get("update_id") is not None else None,
            text_preview=preview,
            created_at=row["created_at"],  # type: ignore[arg-type]
            conversation_status=str(row["conversation_status"]),
            attachment_type=str(row["attachment_type"]) if row.get("attachment_type") else None,
            attachment_status=str(row["attachment_status"]) if row.get("attachment_status") else None,
            current_user_label=label,
            content_statuses=content_statuses,
            runtime_status=runtime_status,
            overall_status=overall,
            has_failure=has_failure,
            has_pending=has_pending,
            has_partial_data=partial,
        )
