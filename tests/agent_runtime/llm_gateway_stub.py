from __future__ import annotations

import json
from typing import Any

from telegram_agent.core.agent_runtime.clients.models import (
    LlmGatewayGeneration,
    LlmGatewayTokenUsage,
)
from telegram_agent.core.agent_runtime.common.models import CoordinatorMessageView


class CoordinatorGatewayAdapter:
    """Adapts decision-script test doubles to the real gateway client boundary."""

    def __init__(self, decision_script: Any) -> None:
        self._decision_script = decision_script
        self.calls: list[dict[str, Any]] = []

    def coordinate_message_group(self, **request: Any) -> LlmGatewayGeneration:
        self.calls.append(request)
        prompt = json.loads(request["user_prompt"])
        current = CoordinatorMessageView.model_validate(prompt["current_message"])
        recent_window = tuple(
            CoordinatorMessageView.model_validate(item)
            for item in prompt["recent_messages_oldest_to_newest"]
        )
        decision = self._decision_script.assign_group(
            current=current,
            recent_window=recent_window,
        )
        return LlmGatewayGeneration(
            request_id="gateway-request",
            output=decision.model_dump(mode="json"),
            provider="test",
            model="test-model",
            usage=LlmGatewayTokenUsage(
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
            ),
        )


def coordinator_gateway(decision_script: Any) -> CoordinatorGatewayAdapter:
    return CoordinatorGatewayAdapter(decision_script)
