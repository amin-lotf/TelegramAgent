from enum import StrEnum


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


class CoordinatorDecisionKind(StrEnum):
    EXISTING = "existing"
    NEW = "new"
    VAGUE = "vague"
