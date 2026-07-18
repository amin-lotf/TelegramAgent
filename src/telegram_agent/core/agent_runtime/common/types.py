from enum import StrEnum

from telegram_agent.core.llm_gateway.common.schemas import (
    MessageGroupingKind as CoordinatorDecisionKind,
)


class CoordinationStatus(StrEnum):
    PENDING = "pending"
    GROUPED = "grouped"
    VAGUE = "vague"


class RuntimeMessageStatus(StrEnum):
    RECEIVED = "received"
    COORDINATING = "coordinating"
    COORDINATED = "coordinated"
    CLASSIFYING = "classifying"
    CLASSIFIED = "classified"
    FAILED = "failed"


class MessageIntent(StrEnum):
    CONVERSATION = "conversation"
    DOWNLOAD_REQUEST = "download_request"


class ClaimStatus(StrEnum):
    IDLE = "idle"
    CLAIMED = "claimed"


class OutboxEventType(StrEnum):
    MESSAGE_PENDING_COORDINATION = "agent_runtime.message.pending_coordination"
    INTENT_CLASSIFIER = "agent_runtime.message.pending_intent_classification"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


__all__ = [
    "ClaimStatus",
    "CoordinationStatus",
    "CoordinatorDecisionKind",
    "MessageIntent",
    "OutboxEventStatus",
    "OutboxEventType",
    "RuntimeMessageStatus",
]
