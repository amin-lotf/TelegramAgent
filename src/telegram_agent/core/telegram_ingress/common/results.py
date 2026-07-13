from dataclasses import dataclass
from uuid import UUID

from telegram_agent.core.telegram_ingress.common.commands import ProcessAttachmentCommand


@dataclass(frozen=True)
class CreateUserMessageResult:
    user_message_id: UUID
    chat_id: int
    attachment_id: UUID | None
    process_attachment_command: ProcessAttachmentCommand | None
    was_created: bool
    @property
    def id(self) -> UUID:
        return self.user_message_id



@dataclass(frozen=True)
class ApplyAttachmentProcessingResultResult:
    applied: bool


@dataclass(frozen=True)
class CoordinateConversationResult:
    outbox_event_id: UUID | None
    message_count: int
    blocked: bool = False


@dataclass(frozen=True)
class OutboxDispatchResult:
    claimed: int = 0
    published: int = 0
    retryable_failures: int = 0
    permanent_failures: int = 0
