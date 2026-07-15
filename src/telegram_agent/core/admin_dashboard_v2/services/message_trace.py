from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, TypeVar
from uuid import UUID

from telegram_agent.core.admin_dashboard_v2.common.exceptions import DataSourceUnavailableError
from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.common.types import (
    DataSourceStatus,
    MessageTraceView,
    SourceResult,
    StageStatus,
)
from telegram_agent.core.admin_dashboard_v2.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard_v2.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_auth import TelegramAuthReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_ingress import TelegramIngressReader
from telegram_agent.core.admin_dashboard_v2.services.redaction import (
    sanitize_text,
    sanitize_trace_data,
)
from telegram_agent.core.admin_dashboard_v2.services.timeline import build_lifecycle_and_timeline


T = TypeVar("T")


class MessageTraceQueryService:
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

    async def get_trace(self, ingress_message_id: UUID) -> MessageTraceView:
        ingress_result, content_result, runtime_result = await asyncio.gather(
            self._read_source(
                self._ingress.source,
                lambda: self._ingress.get_trace(
                    ingress_message_id,
                    sibling_limit=self._settings.maximum_group_siblings,
                ),
            ),
            self._read_source(
                self._content.source,
                lambda: self._content.get_trace(
                    ingress_message_id,
                    attempt_limit=self._settings.maximum_content_attempts,
                    asset_limit=self._settings.maximum_media_assets,
                    outbox_limit=self._settings.maximum_outbox_events,
                    segment_limit=self._settings.maximum_transcript_segments,
                ),
            ),
            self._read_source(
                self._runtime.source,
                lambda: self._runtime.get_trace(
                    ingress_message_id,
                    sibling_limit=self._settings.maximum_group_siblings,
                ),
            ),
        )
        self._mark_canonical_attempts(ingress_result, content_result)
        telegram_user_id = self._resolve_telegram_user_id(
            ingress_result, content_result, runtime_result
        )
        if telegram_user_id is None:
            auth_result: SourceResult[dict[str, Any]] = SourceResult(
                source=self._auth.source,
                status=DataSourceStatus.RECORD_NOT_FOUND,
            )
        else:
            auth_result = await self._read_source(
                self._auth.source,
                lambda: self._auth.get_by_telegram_user_id(telegram_user_id),
            )

        lifecycle, timeline = build_lifecycle_and_timeline(
            ingress_result, content_result, runtime_result
        )
        failures = self._collect_failures(
            ingress_result, content_result, runtime_result
        )
        warnings = self._collect_warnings(
            ingress_result, content_result, runtime_result
        )
        overall = self._overall_status(lifecycle, runtime_result, ingress_result)
        tabs = self._available_tabs(
            ingress_result, content_result, runtime_result, auth_result
        )
        maximum_bytes = self._settings.maximum_raw_json_bytes
        return MessageTraceView(
            ingress_message_id=ingress_message_id,
            ingress=self._sanitized(ingress_result, maximum_bytes),
            content_processing=self._sanitized(content_result, maximum_bytes),
            agent_runtime=self._sanitized(runtime_result, maximum_bytes),
            telegram_auth=self._sanitized(auth_result, maximum_bytes),
            lifecycle=lifecycle,
            timeline=timeline,
            overall_status=overall,
            failures=tuple(failures),
            warnings=tuple(warnings),
            available_tabs=tabs,
        )

    @staticmethod
    async def _read_source(
        source: str,
        operation: Callable[[], Awaitable[T | None]],
    ) -> SourceResult[T]:
        try:
            data = await operation()
        except DataSourceUnavailableError as exc:
            reason = exc.reason.lower()
            status = (
                DataSourceStatus.TIMED_OUT
                if "timed out" in reason
                else DataSourceStatus.INVALID_SCHEMA
                if "schema" in reason
                else DataSourceStatus.NOT_CONFIGURED
                if "not configured" in reason
                else DataSourceStatus.UNAVAILABLE
            )
            return SourceResult(source=source, status=status, message=exc.reason)
        if data is None:
            return SourceResult(source=source, status=DataSourceStatus.RECORD_NOT_FOUND)
        return SourceResult(source=source, status=DataSourceStatus.AVAILABLE, data=data)

    @staticmethod
    def _mark_canonical_attempts(
        ingress: SourceResult[dict[str, Any]],
        content: SourceResult[dict[str, Any]],
    ) -> None:
        attachment = (ingress.data or {}).get("attachment")
        if not attachment or not content.data:
            return
        expected = (
            f"telegram-ingress:process-attachment:{attachment['type']}:"
            f"{attachment['id']}:v1"
        )
        for attempt in content.data.get("attempts", []):
            attempt["canonical_ingress_request"] = attempt.get("idempotency_key") == expected

    @staticmethod
    def _resolve_telegram_user_id(*results: SourceResult[dict[str, Any]]) -> int | None:
        ingress, content, runtime = results
        if ingress.data and ingress.data.get("message"):
            return int(ingress.data["message"]["telegram_user_id"])
        if runtime.data and runtime.data.get("message"):
            return int(runtime.data["message"]["telegram_user_id"])
        attempts = (content.data or {}).get("attempts", [])
        return int(attempts[0]["telegram_user_id"]) if attempts else None

    @staticmethod
    def _collect_failures(
        ingress: SourceResult[dict[str, Any]],
        content: SourceResult[dict[str, Any]],
        runtime: SourceResult[dict[str, Any]],
    ) -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        if ingress.data:
            message = ingress.data.get("message") or {}
            attachment = ingress.data.get("attachment") or {}
            outbox = ingress.data.get("outbox") or {}
            if message.get("conversation_status") == "failed":
                failures.append({"service": "Telegram ingress", "stage": "conversation dispatch", "error": sanitize_text(str(outbox.get("last_error") or "No error detail retained"))})
            if attachment.get("status") == "failed":
                failures.append({"service": "Telegram ingress", "stage": "attachment", "error": "Ingress stores no attachment error detail"})
        for attempt in (content.data or {}).get("attempts", []):
            if attempt.get("status") == "failed":
                failures.append({"service": "Content processing", "stage": "job", "error": sanitize_text(str(attempt.get("error_message") or "No error detail retained"))})
            for event in attempt.get("outbox_events", []):
                if event.get("status") == "failed":
                    failures.append({"service": "Content processing", "stage": str(event.get("event_type")), "error": sanitize_text(str(event.get("last_error") or "No error detail retained"))})
        runtime_outbox = (runtime.data or {}).get("outbox") or {}
        if runtime_outbox.get("status") == "failed":
            failures.append({"service": "Agent runtime", "stage": "coordination", "error": sanitize_text(str(runtime_outbox.get("last_error") or "No error detail retained"))})
        return failures

    @staticmethod
    def _collect_warnings(
        ingress: SourceResult[dict[str, Any]],
        content: SourceResult[dict[str, Any]],
        runtime: SourceResult[dict[str, Any]],
    ) -> list[str]:
        warnings: list[str] = []
        for result in (ingress, content, runtime):
            if not result.available:
                warnings.append(f"{result.source.replace('_', ' ').title()} data is unavailable; this trace is partial.")
        attempts = (content.data or {}).get("attempts", [])
        if len(attempts) > 1:
            warnings.append("Multiple content-processing jobs reference this ingress message; all are shown and no noncanonical job is assumed active.")
        ingress_attachment = (ingress.data or {}).get("attachment") or {}
        runtime_message = (runtime.data or {}).get("message") or {}
        if ingress_attachment and runtime_message.get("attachment_status") and ingress_attachment.get("status") != runtime_message.get("attachment_status"):
            warnings.append("Agent runtime stores the attachment status captured at ingestion; it differs from the current ingress state.")
        if ingress_attachment.get("status") == "failed" and any(attempt.get("status") == "completed" for attempt in attempts):
            warnings.append("Ingress reports a failed attachment while content processing has a completed job, consistent with a lost or failed callback/acceptance response.")
        return warnings

    @staticmethod
    def _overall_status(
        lifecycle: tuple[Any, ...],
        runtime: SourceResult[dict[str, Any]],
        ingress: SourceResult[dict[str, Any]],
    ) -> str:
        authoritative = [stage for stage in lifecycle if stage.status != StageStatus.NOT_IMPLEMENTED]
        if any(stage.status == StageStatus.FAILED for stage in authoritative):
            return "failed"
        if any(stage.status == StageStatus.PENDING for stage in authoritative):
            return "pending"
        runtime_message = (runtime.data or {}).get("message") or {}
        if runtime_message.get("coordination_status") in {"grouped", "vague"}:
            return "coordinated"
        ingress_message = (ingress.data or {}).get("message") or {}
        return str(ingress_message.get("conversation_status") or "partial")

    @staticmethod
    def _available_tabs(*results: SourceResult[dict[str, Any]]) -> tuple[str, ...]:
        return tuple(result.source for result in results if result.data is not None or result.status not in {DataSourceStatus.RECORD_NOT_FOUND, DataSourceStatus.NOT_CONFIGURED})

    @staticmethod
    def _sanitized(result: SourceResult[dict[str, Any]], maximum_bytes: int) -> SourceResult[dict[str, Any]]:
        if result.data is None:
            return result
        return SourceResult(
            source=result.source,
            status=result.status,
            data=sanitize_trace_data(result.data, maximum_bytes=maximum_bytes),
            message=result.message,
        )
