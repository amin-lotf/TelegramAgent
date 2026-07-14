from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from telegram_agent.core.agent_runtime.common.types import CoordinatorDecisionKind
from telegram_agent.core.common.types import TelegramAttachmentType


class CoordinatorMessageView(BaseModel):
    """Coordinator-facing projection of a runtime message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ingress_message_id: UUID
    message_id: int
    reply_message_id: int | None = None
    text: str | None = None
    attachment_type: TelegramAttachmentType | None = None
    group_number: int | None = None


class CoordinatorDecision(BaseModel):
    """Structured coordinator output. Group numbers must come from the window."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: CoordinatorDecisionKind
    group_number: int | None = None

    @model_validator(mode="after")
    def validate_group_number(self) -> "CoordinatorDecision":
        if self.kind == CoordinatorDecisionKind.EXISTING:
            if self.group_number is None or self.group_number < 1:
                raise ValueError("EXISTING decisions require a positive group_number")
        elif self.group_number is not None:
            raise ValueError("Only EXISTING decisions may include group_number")
        return self


class MessageGroupCoordinator(Protocol):
    """Pluggable message-group coordinator (heuristic now, vLLM later)."""

    def assign_group(
        self,
        *,
        current: CoordinatorMessageView,
        recent_window: Sequence[CoordinatorMessageView],
    ) -> CoordinatorDecision:
        """Return existing group number / new / vague for the current message."""
        ...
