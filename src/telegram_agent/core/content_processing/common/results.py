from dataclasses import dataclass
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from telegram_agent.core.content_processing.common.types import JobStatus


class CreateTelegramJobResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    created: bool


@dataclass(frozen=True)
class OutboxDispatchResult:
    claimed: int = 0
    published: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0
