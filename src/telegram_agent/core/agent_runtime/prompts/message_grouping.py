from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from telegram_agent.core.agent_runtime.common.models import CoordinatorMessageView

SYSTEM_PROMPT = """You coordinate incoming messages into semantic conversation groups.

You are given only the latest conversation group (if any). Classify the current message using exactly one decision:
- existing: it clearly continues the latest group's topic or request; use only that group's number from allowed_existing_group_numbers.
- new: it starts a distinct topic/request, is only weakly related, or no latest group is available.
- vague: the message cannot be interpreted at all from the available text and attachment context.

Rules:
- Users do not need to say "new topic". Prefer new when continuity is weak or uncertain between existing and new.
- Chronological proximity alone is not enough for existing.
- Choose existing only when the current message is a clear continuation of the same task (follow-up instruction, answer, clarification, or an attachment the latest group was waiting for).
- Reply routing and the one exclusive-attachment-per-group limit are enforced by the system; do not invent group numbers outside allowed_existing_group_numbers.
- Return only the requested structured result."""


@dataclass(frozen=True, slots=True)
class MessageGroupingPrompts:
    system_prompt: str
    user_prompt: str


def build_message_grouping_prompts(
    *,
    current: CoordinatorMessageView,
    latest_group_messages: Sequence[CoordinatorMessageView],
) -> MessageGroupingPrompts:
    allowed_group_numbers = sorted(
        {
            message.group_number
            for message in latest_group_messages
            if message.group_number is not None
        }
    )
    prompt_data = {
        "current_message": current.model_dump(mode="json"),
        "latest_group_messages_oldest_to_newest": [
            message.model_dump(mode="json") for message in latest_group_messages
        ],
        "allowed_existing_group_numbers": allowed_group_numbers,
    }
    return MessageGroupingPrompts(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(
            prompt_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
