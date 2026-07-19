from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IngestMessageBatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: UUID
    chat_id: int
    created: bool
    message_count: int


class OutboxDispatchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claimed: int
    published: int
    retryable_failures: int
    permanent_failures: int


class ClaimedConversation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    claim_token: UUID


class MessageCoordinationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_message_id: UUID
    status: str
    group_id: UUID | None = None
    group_number: int | None = None


class ConversationCoordinationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    processed: int
    results: tuple[MessageCoordinationResult, ...]


class MessageIntentClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_message_id: UUID
    status: str
    intent: str | None = None


class ConversationIntentClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    processed: int
    results: tuple[MessageIntentClassificationResult, ...]


class MessageDownloadHandlerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_message_id: UUID
    status: str
    early_exit: bool = False
    agent_message_id: UUID | None = None


class ConversationDownloadHandlerResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    processed: int
    results: tuple[MessageDownloadHandlerResult, ...]


class MessageContentProcessingHandoffResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_message_id: UUID
    status: str


class ConversationContentProcessingHandoffResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chat_id: int
    processed: int
    results: tuple[MessageContentProcessingHandoffResult, ...]
