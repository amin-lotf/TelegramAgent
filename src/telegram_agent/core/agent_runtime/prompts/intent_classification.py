from __future__ import annotations

import json
from dataclasses import dataclass

from telegram_agent.core.agent_runtime.common.models import IntentClassifierMessageView

SYSTEM_PROMPT = """Classify the user message into exactly one intent:
- conversation: general chat, questions, or discussion that is not a download request
- download_request: the user wants media or a file downloaded (URL, attachment download, save/get content)

Return only the structured intent. Do not answer the user."""


@dataclass(frozen=True, slots=True)
class IntentClassificationPrompts:
    system_prompt: str
    user_prompt: str


def build_intent_classification_prompts(
    *,
    message: IntentClassifierMessageView,
) -> IntentClassificationPrompts:
    prompt_data = {
        "message": message.model_dump(mode="json"),
    }
    return IntentClassificationPrompts(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(
            prompt_data,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
