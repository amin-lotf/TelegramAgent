from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from telegram_agent.core.agent_runtime.common.models import CoordinatorMessageView

SYSTEM_PROMPT = """You coordinate incoming messages into semantic conversation groups.

Classify the current message using exactly one decision:
- existing: it clearly continues one of the recent grouped topics; use only that group's number.
- new: it starts a distinct topic, or no prior grouped message is available.
- vague: its intended topic cannot be determined confidently from the message and recent window.

Use reply targets, text meaning, attachment context, and chronological proximity as evidence. A direct reply is strong evidence but does not override clearly unrelated content. Attachment-only messages may continue an immediately preceding message that announces or requests the attachment. Never invent a group number. Return only the requested structured result."""


@dataclass(frozen=True, slots=True)
class MessageGroupingPrompts:
    system_prompt: str
    user_prompt: str


def build_message_grouping_prompts(
    *,
    current: CoordinatorMessageView,
    recent_window: Sequence[CoordinatorMessageView],
) -> MessageGroupingPrompts:
    allowed_group_numbers = sorted(
        {
            message.group_number
            for message in recent_window
            if message.group_number is not None
        }
    )
    prompt_data = {
        "current_message": current.model_dump(mode="json"),
        "recent_messages_oldest_to_newest": [
            message.model_dump(mode="json") for message in recent_window
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
