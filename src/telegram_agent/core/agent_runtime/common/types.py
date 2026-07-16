from enum import StrEnum

from telegram_agent.core.llm_gateway.common.schemas import (
    MessageGroupingKind as CoordinatorDecisionKind,
)


class CoordinationStatus(StrEnum):
    PENDING = "pending"
    GROUPED = "grouped"
    VAGUE = "vague"


class ClaimStatus(StrEnum):
    IDLE = "idle"
    CLAIMED = "claimed"


class OutboxEventType(StrEnum):
    MESSAGE_PENDING_COORDINATION = "agent_runtime.message.pending_coordination"


class OutboxEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    PUBLISHED = "published"
    FAILED = "failed"


__all__ = [
    "ClaimStatus",
    "CoordinationStatus",
    "CoordinatorDecisionKind",
    "OutboxEventStatus",
    "OutboxEventType",
]
