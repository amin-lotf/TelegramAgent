from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from datetime import timedelta
from uuid import UUID

from celery import Task

from telegram_agent.core.agent_runtime.common.results import OutboxDispatchResult
from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.agent_runtime.common.types import OutboxEventType
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
from telegram_agent.core.common.exceptions import RetryableAgentRuntimeCoordinationError
from telegram_agent.core.common.utils import utcnow

logger = logging.getLogger(__name__)


class CoordinationOutboxDispatcher:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyAgentRuntimeUnitOfWork],
        ],
        task_by_event_type: Mapping[str, Task],
        batch_size: int,
        claim_lease_timeout: timedelta,
        outbox_lease_timeout: timedelta,
        retry_base_delay: timedelta,
        retry_max_delay: timedelta,
        max_attempts: int,
        process_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._task_by_event_type = dict(task_by_event_type)
        self._batch_size = batch_size
        self._claim_lease_timeout = claim_lease_timeout
        self._outbox_lease_timeout = outbox_lease_timeout
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._max_attempts = max_attempts
        self._process_owner = process_owner or self._default_process_owner()

    @classmethod
    def from_settings(cls) -> "CoordinationOutboxDispatcher":
        from telegram_agent.core.agent_runtime.celery.tasks.classify_intent import (
            classify_intent_task,
        )
        from telegram_agent.core.agent_runtime.celery.tasks.content_processing_handoff import (
            content_processing_handoff_task,
        )
        from telegram_agent.core.agent_runtime.celery.tasks.coordinate_conversation import (
            coordinate_conversation_task,
        )
        from telegram_agent.core.agent_runtime.celery.tasks.download_handler import (
            download_handler_task,
        )

        return cls(
            uow_factory=sync_agent_runtime_uow_factory,
            task_by_event_type={
                OutboxEventType.MESSAGE_PENDING_COORDINATION.value: (
                    coordinate_conversation_task
                ),
                OutboxEventType.INTENT_CLASSIFIER.value: classify_intent_task,
                OutboxEventType.DOWNLOAD_HANDLER.value: download_handler_task,
                OutboxEventType.CONTENT_PROCESSING_HANDOFF.value: (
                    content_processing_handoff_task
                ),
            },
            batch_size=settings.outbox_dispatch_batch_size,
            claim_lease_timeout=timedelta(
                seconds=settings.coordination_claim_lease_seconds
            ),
            outbox_lease_timeout=timedelta(
                seconds=settings.outbox_dispatch_lease_seconds
            ),
            retry_base_delay=timedelta(seconds=settings.outbox_retry_base_seconds),
            retry_max_delay=timedelta(seconds=settings.outbox_retry_max_seconds),
            max_attempts=settings.outbox_max_attempts,
        )

    def dispatch_once(self) -> OutboxDispatchResult:
        with self._uow_factory() as uow:
            recovered_claims = uow.conversation_claims.recover_expired_claims(
                lease_timeout=self._claim_lease_timeout,
            )
            recovered_outbox = uow.outbox_events.recover_expired_leases(
                lease_timeout=self._outbox_lease_timeout,
            )
            claims = uow.conversation_claims.claim_available_conversations(
                batch_size=self._batch_size,
                lease_timeout=self._claim_lease_timeout,
                process_owner=self._process_owner,
            )

        if recovered_claims or recovered_outbox:
            logger.info(
                "Recovered expired agent-runtime coordination leases",
                extra={
                    "recovered_claims": recovered_claims,
                    "recovered_outbox": recovered_outbox,
                },
            )

        published = 0
        retryable_failures = 0
        permanent_failures = 0

        for claim in claims:
            head_event_type: str | None = None
            with self._uow_factory() as uow:
                head = uow.outbox_events.get_head_unresolved_for_chat(
                    chat_id=claim.chat_id
                )
                if head is not None:
                    head_event_type = head.event_type

            if head_event_type is None:
                with self._uow_factory() as uow:
                    uow.conversation_claims.release(
                        chat_id=claim.chat_id,
                        claim_token=claim.claim_token,
                        available_at=utcnow(),
                    )
                logger.warning(
                    "Released claim with no unresolved outbox head",
                    extra={
                        "chat_id": claim.chat_id,
                        "claim_token": str(claim.claim_token),
                    },
                )
                continue

            task = self._task_by_event_type.get(head_event_type)
            if task is None:
                outcome = self._recover_from_enqueue_failure(
                    chat_id=claim.chat_id,
                    claim_token=claim.claim_token,
                    error=RuntimeError(
                        f"Unsupported outbox event type: {head_event_type}"
                    ),
                    force_permanent=True,
                )
                if outcome == "permanent":
                    permanent_failures += 1
                else:
                    retryable_failures += 1
                continue

            try:
                logger.info(
                    "Dispatching agent-runtime outbox task",
                    extra={
                        "chat_id": claim.chat_id,
                        "claim_token": str(claim.claim_token),
                        "event_type": head_event_type,
                        "process_owner": self._process_owner,
                    },
                )
                task.apply_async(
                    args=(claim.chat_id, str(claim.claim_token)),
                )
            except Exception as exc:
                outcome = self._recover_from_enqueue_failure(
                    chat_id=claim.chat_id,
                    claim_token=claim.claim_token,
                    error=exc,
                )
                if outcome == "permanent":
                    permanent_failures += 1
                else:
                    retryable_failures += 1
                continue

            published += 1

        return OutboxDispatchResult(
            claimed=len(claims),
            published=published,
            retryable_failures=retryable_failures,
            permanent_failures=permanent_failures,
        )

    def _recover_from_enqueue_failure(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        error: Exception,
        force_permanent: bool = False,
    ) -> str:
        """Release claim after broker enqueue failure.

        Schedules head outbox retry under the claim token, or promotes the head
        message to permanent failure when retry attempts are exhausted.

        Returns:
            ``"retryable"`` or ``"permanent"`` depending on the outcome.
        """
        try:
            return self._recover_from_enqueue_failure_locked(
                chat_id=chat_id,
                claim_token=claim_token,
                error=error,
                force_permanent=force_permanent,
            )
        except RetryableAgentRuntimeCoordinationError:
            # Permanent transition rolled back; still release the claim so the
            # conversation is not stuck until lease expiry.
            with self._uow_factory() as uow:
                uow.conversation_claims.release(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    available_at=utcnow(),
                )
            logger.warning(
                "Failed to enqueue agent-runtime task; "
                "permanent promotion rolled back, claim released",
                extra={
                    "chat_id": chat_id,
                    "claim_token": str(claim_token),
                    "error": str(error),
                },
            )
            return "retryable"

    def _recover_from_enqueue_failure_locked(
        self,
        *,
        chat_id: int,
        claim_token: UUID,
        error: Exception,
        force_permanent: bool = False,
    ) -> str:
        with self._uow_factory() as uow:
            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
            if head is None:
                uow.conversation_claims.release(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    available_at=utcnow(),
                )
                logger.warning(
                    "Failed to enqueue agent-runtime task; "
                    "no unresolved outbox head",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                        "error": str(error),
                    },
                )
                return "retryable"

            if force_permanent or head.attempt_count >= self._max_attempts:
                exhausted_message = (
                    f"Retry limit exhausted after {head.attempt_count} attempts "
                    f"(broker enqueue failed): {error}"
                    if not force_permanent
                    else str(error)
                )
                if head.event_type == OutboxEventType.MESSAGE_PENDING_COORDINATION.value:
                    # Message first: if outbox fails afterward, the whole UoW rolls back.
                    vague = uow.messages.mark_vague(
                        runtime_message_id=head.runtime_message_id,
                    )
                    if vague is None:
                        uow.conversation_claims.release(
                            chat_id=chat_id,
                            claim_token=claim_token,
                            available_at=utcnow(),
                        )
                        logger.warning(
                            "Enqueue failure exhausted retries but message was not pending",
                            extra={
                                "chat_id": chat_id,
                                "runtime_message_id": str(head.runtime_message_id),
                                "claim_token": str(claim_token),
                                "error": str(error),
                            },
                        )
                        return "permanent"
                elif head.event_type == OutboxEventType.INTENT_CLASSIFIER.value:
                    failed_message = uow.messages.mark_classification_failed(
                        runtime_message_id=head.runtime_message_id,
                    )
                    if failed_message is None:
                        uow.conversation_claims.release(
                            chat_id=chat_id,
                            claim_token=claim_token,
                            available_at=utcnow(),
                        )
                        logger.warning(
                            "Enqueue failure exhausted retries but message was not classifiable",
                            extra={
                                "chat_id": chat_id,
                                "runtime_message_id": str(head.runtime_message_id),
                                "claim_token": str(claim_token),
                                "error": str(error),
                            },
                        )
                        return "permanent"
                elif head.event_type == OutboxEventType.DOWNLOAD_HANDLER.value:
                    failed_message = uow.messages.mark_download_handler_failed(
                        runtime_message_id=head.runtime_message_id,
                    )
                    if failed_message is None:
                        uow.conversation_claims.release(
                            chat_id=chat_id,
                            claim_token=claim_token,
                            available_at=utcnow(),
                        )
                        logger.warning(
                            "Enqueue failure exhausted retries but message was not "
                            "in a coordinated download-ready state",
                            extra={
                                "chat_id": chat_id,
                                "runtime_message_id": str(head.runtime_message_id),
                                "claim_token": str(claim_token),
                                "error": str(error),
                            },
                        )
                        return "permanent"
                elif head.event_type == OutboxEventType.CONTENT_PROCESSING_HANDOFF.value:
                    # Download work already completed; only fail the handoff outbox.
                    pass
                else:
                    uow.conversation_claims.release(
                        chat_id=chat_id,
                        claim_token=claim_token,
                        available_at=utcnow(),
                    )
                    logger.error(
                        "Unsupported outbox event type during permanent enqueue recovery",
                        extra={
                            "chat_id": chat_id,
                            "event_type": head.event_type,
                            "runtime_message_id": str(head.runtime_message_id),
                        },
                    )
                    return "permanent"

                failed = uow.outbox_events.mark_failed_for_message(
                    runtime_message_id=head.runtime_message_id,
                    claim_token=claim_token,
                    error_message=exhausted_message,
                    event_type=head.event_type,
                )
                if failed is None:
                    raise RetryableAgentRuntimeCoordinationError(
                        "Permanent outbox failure update did not apply under active claim"
                    )

                uow.conversation_claims.release(
                    chat_id=chat_id,
                    claim_token=claim_token,
                    available_at=utcnow(),
                )
                logger.error(
                    "Failed to enqueue agent-runtime task; "
                    "retry limit exhausted, marked permanent",
                    extra={
                        "chat_id": chat_id,
                        "claim_token": str(claim_token),
                        "runtime_message_id": str(head.runtime_message_id),
                        "event_type": head.event_type,
                        "attempt_count": head.attempt_count,
                        "max_attempts": self._max_attempts,
                        "error": str(error),
                    },
                )
                return "permanent"

            next_available_at = utcnow() + self._retry_delay(head.attempt_count)
            uow.outbox_events.schedule_dispatch_retry_for_head(
                chat_id=chat_id,
                claim_token=claim_token,
                error_message=f"Broker enqueue failed: {error}",
                next_available_at=next_available_at,
            )
            uow.conversation_claims.release(
                chat_id=chat_id,
                claim_token=claim_token,
                available_at=next_available_at,
            )

        logger.warning(
            "Failed to enqueue agent-runtime task; scheduled retry",
            extra={
                "chat_id": chat_id,
                "claim_token": str(claim_token),
                "error": str(error),
            },
        )
        return "retryable"

    def _retry_delay(self, attempt_count: int) -> timedelta:
        multiplier = 2 ** max(attempt_count, 0)
        delay = self._retry_base_delay * multiplier
        return min(delay, self._retry_max_delay)

    @staticmethod
    def _default_process_owner() -> str:
        return f"{socket.gethostname()}:{os.getpid()}"
