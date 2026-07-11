from uuid import UUID

from pydantic import BaseModel, ConfigDict

from telegram_agent.core.content_processing.common.types import JobStatus


class CreateTelegramJobResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    job_id: UUID
    status: JobStatus
    created: bool