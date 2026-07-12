from dataclasses import dataclass
from uuid import UUID

from telegram_agent.core.telegram_ingress.common.commands import ProcessAttachmentCommand


@dataclass(frozen=True)
class CreateUserMessageResult:
    user_message_id: UUID
    attachment_id: UUID | None
    process_attachment_command: ProcessAttachmentCommand | None
    was_created: bool
    @property
    def id(self) -> UUID:
        return self.user_message_id



@dataclass(frozen=True)
class ApplyAttachmentProcessingResultResult:
    applied: bool
