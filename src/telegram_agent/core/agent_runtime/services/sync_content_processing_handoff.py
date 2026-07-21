from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Any
from uuid import UUID

from telegram_agent.core.agent_runtime.clients.content_processing import (
    ContentProcessingClient,
)
from telegram_agent.core.agent_runtime.common.results import (
    ConversationContentProcessingHandoffResult,
    MessageContentProcessingHandoffResult,
)
from telegram_agent.core.agent_runtime.common.settings import Settings, settings
from telegram_agent.core.agent_runtime.common.types import OutboxEventType
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
from telegram_agent.core.common.exceptions import (
    ContentProcessingBadResponseError,
    ContentProcessingUnavailableError,
    PermanentAgentRuntimeCoordinationError,
    RetryableAgentRuntimeCoordinationError,
)
from telegram_agent.core.common.utils import utcnow

logger = logging.getLogger(__name__)


class SyncContentProcessingHandoffService:
    """Thin outbox consumer that hands download requests to content processing.

    Does not create DownloadJob tables; that remains content-processing ownership.
    """

    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyAgentRuntimeUnitOfWork],
        ],
        content_processing_client: ContentProcessingClient,
        settings: Settings,
    ) -> None:
        self._uow_factory = uow_factory
        self._content_processing_client = content_processing_client
        self._settings = settings

    @classmethod
    def from_settings(
        cls,
        *,
        content_processing_client: ContentProcessingClient | None = None,
    ) -> "SyncContentProcessingHandoffService":
        if content_processing_client is None:
            content_processing_client = ContentProcessingClient(
                base_url=settings.content_processing_base_url,
                token=settings.content_processing_service_token,
                timeout_seconds=settings.content_processing_request_timeout_seconds,
            )
        return cls(
            uow_factory=sync_agent_runtime_uow_factory,
            content_processing_client=content_processing_client,
            settings=settings,
        )

    def process_conversation(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
    ) -> ConversationContentProcessingHandoffResult:
        lease_timeout = timedelta(
            seconds=self._settings.coordination_claim_lease_seconds
        )

        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                logger.info(
                    "Skipping content-processing handoff without a valid claim token",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                    },
                )
                return ConversationContentProcessingHandoffResult(
                    chat_id=chat_id,
                    processed=0,
                    results=(),
                )

            pending_events = uow.outbox_events.list_unresolved_for_chat_by_type(
                chat_id=chat_id,
                event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
                limit=self._settings.coordination_message_batch_size,
            )
            event_ids = [event.id for event in pending_events]

        results: list[MessageContentProcessingHandoffResult] = []
        try:
            for event_id in event_ids:
                with self._uow_factory() as uow:
                    renewed = uow.conversation_claims.renew(
                        chat_id=chat_id,
                        claim_token=claim_token,
                        lease_timeout=lease_timeout,
                    )
                    if renewed is None:
                        logger.info(
                            "Stopping content-processing handoff; "
                            "claim token no longer valid",
                            extra={
                                "chat_id": chat_id,
                                "claim_token": str(claim_token),
                            },
                        )
                        return ConversationContentProcessingHandoffResult(
                            chat_id=chat_id,
                            processed=len(results),
                            results=tuple(results),
                        )

                result = self._handoff_single_event(
                    chat_id=chat_id,
                    event_id=event_id,
                    claim_token=claim_token,
                    lease_timeout=lease_timeout,
                )
                if result is None:
                    break
                results.append(result)
        finally:
            with self._uow_factory() as uow:
                uow.conversation_claims.release(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    available_at=utcnow(),
                )

        return ConversationContentProcessingHandoffResult(
            chat_id=chat_id,
            processed=len(results),
            results=tuple(results),
        )

    def _handoff_single_event(
        self,
        *,
        chat_id: int,
        event_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageContentProcessingHandoffResult | None:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                return None

            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
            if head is None or head.id != event_id:
                return None
            if head.event_type != OutboxEventType.CONTENT_PROCESSING_HANDOFF.value:
                return None

            payload = dict(head.payload)
            runtime_message_id = head.runtime_message_id
            idempotency_key = head.idempotency_key

        try:
            self._call_content_processing(payload=payload, idempotency_key=idempotency_key)
            return self._mark_published(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            )
        except PermanentAgentRuntimeCoordinationError as exc:
            self._record_permanent_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
                error=exc,
            )
            return None
        except RetryableAgentRuntimeCoordinationError as exc:
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error=exc,
            )
            return None
        except Exception as exc:
            self._record_retryable_failure(
                chat_id=chat_id,
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error=exc,
            )
            logger.exception(
                "Unexpected content-processing handoff failure",
                extra={
                    "chat_id": chat_id,
                    "runtime_message_id": str(runtime_message_id),
                },
            )
            return None

    def _call_content_processing(
        self,
        *,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> None:
        # Back-compat: older outbox rows nested fields under "extraction".
        extraction = payload.get("extraction")
        if isinstance(extraction, dict):
            for key in (
                "assistant_text",
                "requested_subtitle_language",
                "requested_dub_language",
                "requested_language",
                "requested_format",
            ):
                if key not in payload and key in extraction:
                    payload[key] = extraction[key]

        try:
            chat_id = int(payload["chat_id"])
            telegram_user_id = int(payload["telegram_user_id"])
            group_id = UUID(str(payload["group_id"]))
            agent_message_id = UUID(str(payload["agent_message_id"]))
            media_ingress_message_id = UUID(str(payload["media_ingress_message_id"]))
            media_type = str(payload["media_type"])
            assistant_text = str(payload["assistant_text"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentAgentRuntimeCoordinationError(
                "Invalid content-processing handoff payload"
            ) from exc

        try:
            common = {
                "chat_id": chat_id,
                "telegram_user_id": telegram_user_id,
                "group_id": group_id,
                "agent_message_id": agent_message_id,
                "media_ingress_message_id": media_ingress_message_id,
                "assistant_text": assistant_text,
                "idempotency_key": idempotency_key,
            }
            if media_type == "video":
                self._content_processing_client.submit_video_download(
                    **common,
                    requested_subtitle_language=_optional_str(
                        payload.get("requested_subtitle_language")
                    ),
                    requested_dub_language=_optional_str(
                        payload.get("requested_dub_language")
                    ),
                )
            elif media_type == "audio":
                self._content_processing_client.submit_audio_download(
                    **common,
                    requested_language=_optional_str(payload.get("requested_language")),
                )
            elif media_type == "document":
                # When the user asks for subtitles/translation on a Telegram
                # document (common for MKV), use the video download pipeline.
                subtitle = _optional_str(payload.get("requested_subtitle_language"))
                dub = _optional_str(payload.get("requested_dub_language"))
                if subtitle or dub:
                    self._content_processing_client.submit_video_download(
                        **common,
                        requested_subtitle_language=subtitle,
                        requested_dub_language=dub,
                    )
                else:
                    self._content_processing_client.submit_document_download(
                        **common,
                        requested_format=_optional_str(payload.get("requested_format")),
                    )
            else:
                raise PermanentAgentRuntimeCoordinationError(
                    f"Unsupported download media_type for handoff: {media_type}"
                )
        except ContentProcessingUnavailableError as exc:
            raise RetryableAgentRuntimeCoordinationError(str(exc)) from exc
        except ContentProcessingBadResponseError as exc:
            raise PermanentAgentRuntimeCoordinationError(str(exc)) from exc

    def _mark_published(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
    ) -> MessageContentProcessingHandoffResult:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                raise RetryableAgentRuntimeCoordinationError(
                    "Claim token is no longer valid"
                )

            published = uow.outbox_events.mark_published_for_message(
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
            )
            if published is None:
                raise RetryableAgentRuntimeCoordinationError(
                    "Failed to mark content-processing handoff outbox published "
                    "under active claim"
                )

        return MessageContentProcessingHandoffResult(
            runtime_message_id=runtime_message_id,
            status="published",
        )

    def _record_retryable_failure(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        error: Exception,
    ) -> None:
        with self._uow_factory() as uow:
            event = uow.outbox_events.get_by_runtime_message_id(
                runtime_message_id,
                event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
            )
            attempt_count = 0 if event is None else event.attempt_count

            if attempt_count < self._settings.outbox_max_attempts:
                next_available_at = utcnow() + self._retry_delay(attempt_count)
                updated = uow.outbox_events.record_failure_for_message(
                    runtime_message_id=runtime_message_id,
                    claim_token=claim_token,
                    error_message=str(error),
                    next_available_at=next_available_at,
                    event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
                )
                if updated is None:
                    return
                logger.warning(
                    "Retryable content-processing handoff failure",
                    extra={
                        "chat_id": chat_id,
                        "runtime_message_id": str(runtime_message_id),
                        "attempt_count": updated.attempt_count,
                        "error": str(error),
                    },
                )
                return

        exhausted = RetryableAgentRuntimeCoordinationError(
            f"Retry limit exhausted after {attempt_count} attempts: {error}"
        )
        exhausted.__cause__ = error
        # Permanent path without mutating RuntimeMessage status further —
        # download work already completed; only handoff is failing.
        with self._uow_factory() as uow:
            uow.outbox_events.mark_failed_for_message(
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error_message=str(exhausted),
                event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
            )
        logger.error(
            "Permanent content-processing handoff failure",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "error": str(exhausted),
            },
        )

    def _record_permanent_failure(
        self,
        *,
        chat_id: int,
        runtime_message_id: UUID,
        claim_token: UUID,
        lease_timeout: timedelta,
        error: Exception,
    ) -> None:
        with self._uow_factory() as uow:
            if not uow.conversation_claims.verify_claim(
                chat_id=chat_id,
                claim_token=claim_token,
                lease_timeout=lease_timeout,
            ):
                return
            uow.outbox_events.mark_failed_for_message(
                runtime_message_id=runtime_message_id,
                claim_token=claim_token,
                error_message=str(error),
                event_type=OutboxEventType.CONTENT_PROCESSING_HANDOFF,
            )
        logger.error(
            "Permanent content-processing handoff failure",
            extra={
                "chat_id": chat_id,
                "runtime_message_id": str(runtime_message_id),
                "error": str(error),
            },
        )

    def _retry_delay(self, attempt_count: int) -> timedelta:
        base = timedelta(seconds=self._settings.outbox_retry_base_seconds)
        maximum = timedelta(seconds=self._settings.outbox_retry_max_seconds)
        delay = base * (2 ** max(attempt_count, 0))
        return min(delay, maximum)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
