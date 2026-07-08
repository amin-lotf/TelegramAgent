from typing import Literal

from pydantic import BaseModel, ConfigDict


class ProcessAttachmentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted"]