from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import timedelta
from typing import Callable
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from telegram_agent.core.common.exceptions import (
    EmbeddingResponseError,
    EmbeddingServiceError,
    PermanentContentProcessingError,
    RetryableContentProcessingError,
)
from telegram_agent.core.content_processing.clients.embedding_client import EmbeddingClient
from telegram_agent.core.content_processing.common.commands import (
    RecordChunkEmbeddingCommand,
    RecordChunkEmbeddingsCommand,
)
from telegram_agent.core.content_processing.common.const import (
    DEFAULT_EMBEDDING_CLIENT_BATCH_SIZE,
    DEFAULT_EMBEDDING_VECTOR_DIMENSIONS,
)
from telegram_agent.core.content_processing.common.results import (
    EmbeddingChunkInput,
    EmbeddingResult,
    StageExecutionResult,
)
from telegram_agent.core.content_processing.common.settings import Settings, settings
from telegram_agent.core.content_processing.common.types import (
    ContentChunkType,
    JobStatus,
    OutboxEventType,
)
from telegram_agent.core.content_processing.db.models.content_processing import OutboxEvent
from telegram_agent.core.content_processing.db.uow.sync_content_processing import (
    SyncSqlAlchemyContentProcessingUnitOfWork,
)


class SyncEmbeddingService:
    def __init__(
        self,
        *,
        uow_factory: Callable[
            [],
            AbstractContextManager[SyncSqlAlchemyContentProcessingUnitOfWork],
        ],
        settings: Settings,
        embedding_client: EmbeddingClient | None = None,
        batch_size: int = DEFAULT_EMBEDDING_CLIENT_BATCH_SIZE,
    ) -> None:
        self._uow_factory = uow_factory
        self._settings = settings
        self._embedding_client = embedding_client or EmbeddingClient(settings)
        self._batch_size = max(1, batch_size)

    @classmethod
    def from_settings(cls) -> "SyncEmbeddingService":
        from telegram_agent.core.content_processing.db.uow.sync_uow_factory import (
            sync_content_processing_uow_factory,
        )

        return cls(
            uow_factory=sync_content_processing_uow_factory,
            settings=settings,
        )

    def execute(self, *, job_id: UUID, retry_count: int) -> StageExecutionResult:
        try:
            context_chunks = self._claim_and_resolve(job_id)
            if context_chunks is None:
                result = StageExecutionResult()
            else:
                embedding_result = self._embed_all(context_chunks)
                self._record_success(job_id=job_id, result=embedding_result)
                result = StageExecutionResult()
        except PermanentContentProcessingError as exc:
            self._mark_failed(job_id, str(exc))
            result = StageExecutionResult(error_message=str(exc))
        except (RetryableContentProcessingError, SQLAlchemyError) as exc:
            result = self._retry_or_fail(
                job_id=job_id,
                retry_count=retry_count,
                error_message=str(exc),
            )

        self._enqueue_terminal_callback(job_id)
        return result

    def _embed_all(
        self,
        chunks: tuple[EmbeddingChunkInput, ...],
    ) -> EmbeddingResult:
        if not chunks:
            raise PermanentContentProcessingError("No chunks available for embedding")

        all_items: list = []
        provider = ""
        model = ""
        dimensions = DEFAULT_EMBEDDING_VECTOR_DIMENSIONS

        for start in range(0, len(chunks), self._batch_size):
            batch = chunks[start : start + self._batch_size]
            try:
                batch_result = self._embedding_client.embed_chunks(chunks=batch)
            except EmbeddingServiceError as exc:
                raise RetryableContentProcessingError(str(exc)) from exc
            except EmbeddingResponseError as exc:
                raise PermanentContentProcessingError(str(exc)) from exc

            if batch_result.dimensions != DEFAULT_EMBEDDING_VECTOR_DIMENSIONS:
                raise PermanentContentProcessingError(
                    "Embedding service returned unsupported dimensions "
                    f"{batch_result.dimensions}; expected "
                    f"{DEFAULT_EMBEDDING_VECTOR_DIMENSIONS}"
                )
            if batch_result.count != len(batch):
                raise PermanentContentProcessingError(
                    "Embedding service returned unexpected embedding count"
                )

            provider = batch_result.provider
            model = batch_result.model
            dimensions = batch_result.dimensions
            all_items.extend(batch_result.embeddings)

        return EmbeddingResult(
            provider=provider,
            model=model,
            dimensions=dimensions,
            count=len(all_items),
            embeddings=tuple(all_items),
        )

    def _retry_or_fail(
        self,
        *,
        job_id: UUID,
        retry_count: int,
        error_message: str,
    ) -> StageExecutionResult:
        if retry_count >= self._settings.media_task_max_retries:
            message = "Embedding retry limit exhausted"
            self._mark_failed(job_id, message)
            return StageExecutionResult(error_message=message)
        self._mark_retryable(job_id, error_message)
        return StageExecutionResult(retryable=True, error_message=error_message)

    def _claim_and_resolve(
        self,
        job_id: UUID,
    ) -> tuple[EmbeddingChunkInput, ...] | None:
        with self._uow_factory() as uow:
            if not uow.jobs.claim_embedding(
                job_id=job_id,
                lease_timeout=timedelta(
                    seconds=self._settings.media_processing_lease_seconds
                ),
            ):
                return None

            if uow.chunk_embeddings.count_for_job(job_id=job_id) > 0:
                if not uow.jobs.complete_embedding(job_id=job_id):
                    raise RetryableContentProcessingError(
                        "Existing embeddings could not be applied to job state"
                    )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            chunks = uow.content_chunks.list_for_job(
                job_id=job_id,
                content_type=ContentChunkType.TRANSCRIPT,
            )
            if not chunks:
                # No text chunks → nothing to embed; finish successfully.
                if not uow.jobs.complete_embedding(job_id=job_id):
                    raise RetryableContentProcessingError(
                        "Empty-chunk embedding completion could not be applied"
                    )
                uow.job_expectations.mark_satisfied(job_id=job_id)
                self._enqueue_terminal_callback_in_uow(uow, job_id)
                return None

            return tuple(
                EmbeddingChunkInput(chunk_id=str(chunk.id), text=chunk.text)
                for chunk in chunks
            )

    def _record_success(self, *, job_id: UUID, result: EmbeddingResult) -> None:
        try:
            command = RecordChunkEmbeddingsCommand(
                job_id=job_id,
                embeddings=tuple(
                    RecordChunkEmbeddingCommand(
                        chunk_id=UUID(item.chunk_id),
                        provider=result.provider,
                        model=result.model,
                        dimensions=item.dimensions,
                        embedding=item.embedding,
                    )
                    for item in result.embeddings
                ),
            )
        except (TypeError, ValueError) as exc:
            raise PermanentContentProcessingError(
                "Embedding service returned an invalid chunk_id"
            ) from exc

        with self._uow_factory() as uow:
            if not uow.chunk_embeddings.record(command):
                raise RetryableContentProcessingError(
                    "Embedding result could not be persisted"
                )
            if not uow.jobs.complete_embedding(job_id=job_id):
                raise RetryableContentProcessingError(
                    "Embedding result could not be applied to job state"
                )
            uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)

    def _enqueue_terminal_callback(self, job_id: UUID) -> None:
        with self._uow_factory() as uow:
            self._enqueue_terminal_callback_in_uow(uow, job_id)

    @staticmethod
    def _enqueue_terminal_callback_in_uow(
        uow: SyncSqlAlchemyContentProcessingUnitOfWork,
        job_id: UUID,
    ) -> None:
        job = uow.jobs.get_by_id(job_id)
        if (
            job is None
            or not job.callback_required
            or job.status
            not in (
                JobStatus.EMBEDDED,
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.TIMED_OUT,
            )
        ):
            return

        event_type = OutboxEventType.CONTENT_PROCESSING_JOB_FINISHED
        idempotency_key = f"{event_type.value}:{job_id}"
        if uow.outbox_events.get_by_idempotency_key(idempotency_key) is None:
            uow.outbox_events.add(
                OutboxEvent(
                    event_type=event_type,
                    job_id=job_id,
                    idempotency_key=idempotency_key,
                    payload={},
                )
            )

    def _mark_retryable(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            uow.jobs.mark_embedding_retryable(
                job_id=job_id,
                error_message=error_message,
            )

    def _mark_failed(self, job_id: UUID, error_message: str) -> None:
        with self._uow_factory() as uow:
            if uow.jobs.mark_failed(job_id=job_id, error_message=error_message):
                uow.job_expectations.mark_satisfied(job_id=job_id)
            self._enqueue_terminal_callback_in_uow(uow, job_id)
