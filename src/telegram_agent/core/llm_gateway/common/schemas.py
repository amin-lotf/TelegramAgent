from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageGroupingKind(StrEnum):
    EXISTING = "existing"
    NEW = "new"
    VAGUE = "vague"


class MessageGroupingResponse(BaseModel):
    """Fixed structured-output schema for message-group coordination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: MessageGroupingKind
    group_number: int | None = Field(default=None)

    @model_validator(mode="after")
    def validate_group_number(self) -> "MessageGroupingResponse":
        if self.kind == MessageGroupingKind.EXISTING:
            if self.group_number is None or self.group_number < 1:
                raise ValueError("EXISTING decisions require a positive group_number")
        elif self.group_number is not None:
            raise ValueError("Only EXISTING decisions may include group_number")
        return self
