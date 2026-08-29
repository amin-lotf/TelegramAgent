from typing import Literal

from pydantic import BaseModel, ConfigDict
from uuid import UUID


class ProcessAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]


class AgentRuntimeAcceptedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]


class CancelAllSecondaryTasksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["registered"]
    cancellation_id: UUID
    cutoff_message_id: int
    matched_active_count: int
