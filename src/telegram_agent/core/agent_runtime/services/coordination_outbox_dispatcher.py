from __future__ import annotations

import logging
import os
import socket
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta

from celery import Task

from telegram_agent.core.agent_runtime.common.results import OutboxDispatchResult
from telegram_agent.core.agent_runtime.common.settings import settings
from telegram_agent.core.agent_runtime.db.uow.sync_agent_runtime import (
    SyncSqlAlchemyAgentRuntimeUnitOfWork,
)
from telegram_agent.core.agent_runtime.db.uow.sync_uow_factory import (
    sync_agent_runtime_uow_factory,
)
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
        coordinate_task: Task,
        batch_size: int,
        claim_lease_timeout: timedelta,
        outbox_lease_timeout: timedelta,
        retry_base_delay: timedelta,
        retry_max_delay: timedelta,
        process_owner: str | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._coordinate_task = coordinate_task
        self._batch_size = batch_size
        self._claim_lease_timeout = claim_lease_timeout
        self._outbox_lease_timeout = outbox_lease_timeout
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay
        self._process_owner = process_owner or self._default_process_owner()

    @classmethod
    def from_settings(cls) -> "CoordinationOutboxDispatcher":
        from telegram_agent.core.agent_runtime.celery.tasks.coordinate_conversation import (
            coordinate_conversation_task,
        )

        return cls(
            uow_factory=sync_agent_runtime_uow_factory,
            coordinate_task=coordinate_conversation_task,
            batch_size=settings.outbox_dispatch_batch_size,
            claim_lease_timeout=timedelta(
                seconds=settings.coordination_claim_lease_seconds
            ),
            outbox_lease_timeout=timedelta(
                seconds=settings.outbox_dispatch_lease_seconds
            ),
            retry_base_delay=timedelta(seconds=settings.outbox_retry_base_seconds),
            retry_max_delay=timedelta(seconds=settings.outbox_retry_max_seconds),
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
            try:
                logger.info(
                    "Dispatching conversation coordination task",
                    extra={
                        "chat_id": claim.chat_id,
                        "claim_token": str(claim.claim_token),
                        "process_owner": self._process_owner,
                    },
                )
                self._coordinate_task.apply_async(
                    args=(claim.chat_id, str(claim.claim_token)),
                )
            except Exception as exc:
                retryable_failures += 1
                self._recover_from_enqueue_failure(
                    chat_id=claim.chat_id,
                    claim_token=claim.claim_token,
                    error=exc,
                )
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
        claim_token,
        error: Exception,
    ) -> None:
        """Release claim and schedule head outbox retry under the claim token."""
        with self._uow_factory() as uow:
            head = uow.outbox_events.get_head_unresolved_for_chat(chat_id=chat_id)
            attempt_count = 0 if head is None else head.attempt_count
            next_available_at = utcnow() + self._retry_delay(attempt_count)

            if head is not None:
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
            "Failed to enqueue conversation coordination task; scheduled retry",
            extra={
                "chat_id": chat_id,
                "claim_token": str(claim_token),
                "error": str(error),
            },
        )

    def _retry_delay(self, attempt_count: int) -> timedelta:
        multiplier = 2 ** max(attempt_count, 0)
        delay = self._retry_base_delay * multiplier
        return min(delay, self._retry_max_delay)

    @staticmethod
    def _default_process_owner() -> str:
        return f"{socket.gethostname()}:{os.getpid()}"
