"""Cross-service message trace coordinator."""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from telegram_agent.core.admin_dashboard.common.settings import Settings
from telegram_agent.core.admin_dashboard.common.types import DbAvailability, DbName
from telegram_agent.core.admin_dashboard.db.engines import DashboardDatabases
from telegram_agent.core.admin_dashboard.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard.db.readers.telegram_auth import AuthReader
from telegram_agent.core.admin_dashboard.db.readers.telegram_ingress import IngressReader
from telegram_agent.core.admin_dashboard.services.overall_state import (
    derive_overall_state,
    overall_state_label,
)
from telegram_agent.core.admin_dashboard.services.redact import mask_path, text_preview
from telegram_agent.core.admin_dashboard.services.timeline import build_timeline
from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    AuthUserRow,
    ContentProcessingView,
    FailureInfo,
    MediaAssetRow,
    MessageTrace,
    OutboxRow,
    RuntimeMessageRow,
    UserMessageRow,
)

logger = logging.getLogger(__name__)


class MessageTraceService:
    def __init__(self, databases: DashboardDatabases, settings: Settings) -> None:
        self._databases = databases
        self._settings = settings

    async def get_trace(self, ingress_message_id: UUID) -> MessageTrace:
        availability: dict[DbName, DbAvailability] = {
            DbName.INGRESS: DbAvailability.OK,
            DbName.CONTENT_PROCESSING: DbAvailability.SKIPPED,
            DbName.AGENT_RUNTIME: DbAvailability.SKIPPED,
            DbName.AUTH: DbAvailability.SKIPPED,
        }
        failures: list[FailureInfo] = []

        message, ingress_outbox, ingress_status = await self._load_ingress(ingress_message_id)
        availability[DbName.INGRESS] = ingress_status
        if ingress_status != DbAvailability.OK:
            return MessageTrace(
                found=False,
                ingress_message_id=ingress_message_id,
                overall_state=derive_overall_state(message=None, content=None, runtime=None),
                overall_state_label=overall_state_label(
                    derive_overall_state(message=None, content=None, runtime=None)
                ),
                ingress=None,
                ingress_outbox=None,
                content_processing=None,
                agent_runtime=None,
                auth_user=None,
                timeline=(),
                failures=(
                    FailureInfo(
                        source="ingress",
                        message=f"Ingress database {ingress_status.value}",
                        status=ingress_status.value,
                    ),
                ),
                db_availability=availability,
            )

        if message is None:
            return MessageTrace(
                found=False,
                ingress_message_id=ingress_message_id,
                overall_state=derive_overall_state(message=None, content=None, runtime=None),
                overall_state_label=overall_state_label(
                    derive_overall_state(message=None, content=None, runtime=None)
                ),
                ingress=None,
                ingress_outbox=None,
                content_processing=None,
                agent_runtime=None,
                auth_user=None,
                timeline=(),
                failures=(),
                db_availability=availability,
            )

        content_task = asyncio.create_task(self._load_content(message))
        runtime_task = asyncio.create_task(self._load_runtime(ingress_message_id, message.chat_id))
        auth_task = asyncio.create_task(self._load_auth(message.telegram_user_id))

        content, content_status = await content_task
        runtime, runtime_status = await runtime_task
        auth_user, auth_status = await auth_task

        availability[DbName.CONTENT_PROCESSING] = content_status
        availability[DbName.AGENT_RUNTIME] = runtime_status
        availability[DbName.AUTH] = auth_status

        if content_status in {DbAvailability.ERROR, DbAvailability.TIMEOUT}:
            failures.append(
                FailureInfo(
                    source="content_processing",
                    message=f"Content-processing database {content_status.value}",
                    status=content_status.value,
                )
            )
        if runtime_status in {DbAvailability.ERROR, DbAvailability.TIMEOUT}:
            failures.append(
                FailureInfo(
                    source="agent_runtime",
                    message=f"Agent-runtime database {runtime_status.value}",
                    status=runtime_status.value,
                )
            )

        if message.attachment is not None and message.attachment.status == "failed":
            failures.append(
                FailureInfo(
                    source="ingress.attachment",
                    message="Attachment status is failed",
                    status="failed",
                )
            )
        if message.conversation_status == "failed":
            failures.append(
                FailureInfo(
                    source="ingress.conversation",
                    message="Conversation status is failed",
                    status="failed",
                )
            )
        if content is not None and content.job is not None and content.job.error_message:
            failures.append(
                FailureInfo(
                    source="content_processing.job",
                    message=content.job.error_message,
                    status=content.job.status,
                )
            )
        if ingress_outbox is not None and ingress_outbox.last_error:
            failures.append(
                FailureInfo(
                    source="ingress.outbox",
                    message=ingress_outbox.last_error,
                    status=ingress_outbox.status,
                )
            )
        if runtime is not None:
            if runtime.message is not None and runtime.message.status == "failed":
                detail = "Pipeline status is failed"
                if runtime.message.intent:
                    detail = f"{detail} (intent={runtime.message.intent})"
                failures.append(
                    FailureInfo(
                        source="agent_runtime.pipeline",
                        message=detail,
                        status=runtime.message.status,
                    )
                )
            outbox_events = runtime.outbox_events or (
                (runtime.outbox,) if runtime.outbox is not None else ()
            )
            for event in outbox_events:
                if event.last_error or event.status == "failed":
                    failures.append(
                        FailureInfo(
                            source=f"agent_runtime.outbox:{event.event_type}",
                            message=event.last_error or "Outbox event failed",
                            status=event.status,
                        )
                    )

        state = derive_overall_state(message=message, content=content, runtime=runtime)
        timeline = build_timeline(
            message=message,
            ingress_outbox=ingress_outbox,
            content=content,
            runtime=runtime,
            cp_available=content_status == DbAvailability.OK,
            runtime_available=runtime_status == DbAvailability.OK,
        )

        return MessageTrace(
            found=True,
            ingress_message_id=message.id,
            overall_state=state,
            overall_state_label=overall_state_label(state),
            ingress=message,
            ingress_outbox=ingress_outbox,
            content_processing=content,
            agent_runtime=runtime,
            auth_user=auth_user,
            timeline=timeline,
            failures=tuple(failures),
            db_availability=availability,
            text_preview=text_preview(
                message.text,
                mask=self._settings.mask_message_text,
            ),
        )

    async def _load_ingress(
        self,
        ingress_message_id: UUID,
    ) -> tuple[UserMessageRow | None, OutboxRow | None, DbAvailability]:
        try:
            async with self._databases.session(DbName.INGRESS) as session:
                reader = IngressReader(session)

                async def _load() -> tuple[UserMessageRow | None, OutboxRow | None]:
                    message = await reader.get_message(ingress_message_id)
                    if message is None or message.dispatch_event_id is None:
                        return message, None
                    outbox = await reader.get_outbox(message.dispatch_event_id)
                    return message, outbox

                message, outbox = await asyncio.wait_for(
                    _load(),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return message, outbox, DbAvailability.OK
        except TimeoutError:
            logger.warning("Ingress trace query timed out")
            return None, None, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Ingress trace query failed")
            return None, None, DbAvailability.ERROR

    async def _load_content(
        self,
        message: UserMessageRow,
    ) -> tuple[ContentProcessingView | None, DbAvailability]:
        if message.attachment is None:
            return (
                ContentProcessingView(
                    job=None,
                    source=None,
                    not_applicable=True,
                ),
                DbAvailability.SKIPPED,
            )
        try:
            async with self._databases.session(DbName.CONTENT_PROCESSING) as session:
                reader = ContentProcessingReader(session)

                async def _load() -> ContentProcessingView:
                    source = await reader.get_source_by_ingress_message_id(message.id)
                    if source is None:
                        return ContentProcessingView(job=None, source=None)
                    job = await reader.get_job(source.job_id)
                    assets = await reader.list_assets(source.job_id)
                    outbox_events = await reader.list_outbox(source.job_id)
                    transcript = await reader.get_transcript(source.job_id)
                    masked_assets = tuple(
                        MediaAssetRow(
                            id=asset.id,
                            job_id=asset.job_id,
                            role=asset.role,
                            parent_asset_id=asset.parent_asset_id,
                            local_path=mask_path(
                                asset.local_path,
                                enabled=self._settings.mask_media_paths,
                            ),
                            media_type=asset.media_type,
                            mime_type=asset.mime_type,
                            duration_ms=asset.duration_ms,
                            size_bytes=asset.size_bytes,
                        )
                        for asset in assets
                    )
                    return ContentProcessingView(
                        job=job,
                        source=source,
                        assets=masked_assets,
                        outbox_events=tuple(outbox_events),
                        transcript=transcript,
                    )

                view = await asyncio.wait_for(
                    _load(),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return view, DbAvailability.OK
        except TimeoutError:
            logger.warning("Content-processing trace query timed out")
            return None, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Content-processing trace query failed")
            return None, DbAvailability.ERROR

    async def _load_runtime(
        self,
        ingress_message_id: UUID,
        chat_id: int,
    ) -> tuple[AgentRuntimeView | None, DbAvailability]:
        try:
            async with self._databases.session(DbName.AGENT_RUNTIME) as session:
                reader = AgentRuntimeReader(session)

                async def _load() -> AgentRuntimeView:
                    message = await reader.get_message_by_ingress_id(ingress_message_id)
                    if message is None:
                        return AgentRuntimeView(
                            message=None,
                            batch=None,
                            group=None,
                            outbox=None,
                            claim=None,
                            group_messages=(),
                            outbox_events=(),
                        )
                    batch = await reader.get_batch(message.batch_id)
                    group = (
                        await reader.get_group(message.group_id)
                        if message.group_id is not None
                        else None
                    )
                    group_messages: tuple[RuntimeMessageRow, ...] = ()
                    if message.group_id is not None:
                        group_messages = tuple(
                            await reader.list_messages_by_group_id(message.group_id)
                        )
                    outbox_events = tuple(
                        await reader.list_outbox_for_message(message.id)
                    )
                    outbox = await reader.get_outbox_for_message(message.id)
                    claim = await reader.get_claim(chat_id)
                    return AgentRuntimeView(
                        message=message,
                        batch=batch,
                        group=group,
                        outbox=outbox,
                        claim=claim,
                        group_messages=group_messages,
                        outbox_events=outbox_events,
                    )

                view = await asyncio.wait_for(
                    _load(),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return view, DbAvailability.OK
        except TimeoutError:
            logger.warning("Agent-runtime trace query timed out")
            return None, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Agent-runtime trace query failed")
            return None, DbAvailability.ERROR

    async def _load_auth(
        self,
        telegram_user_id: int,
    ) -> tuple[AuthUserRow | None, DbAvailability]:
        if not self._settings.enable_auth_db_enrichment:
            return None, DbAvailability.SKIPPED
        try:
            async with self._databases.session(DbName.AUTH) as session:
                reader = AuthReader(session)
                user = await asyncio.wait_for(
                    reader.get_by_telegram_user_id(telegram_user_id),
                    timeout=self._settings.db_query_timeout_seconds,
                )
            return user, DbAvailability.OK
        except TimeoutError:
            return None, DbAvailability.TIMEOUT
        except Exception:
            logger.exception("Auth enrichment failed")
            return None, DbAvailability.ERROR
