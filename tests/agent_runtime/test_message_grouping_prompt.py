from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from telegram_agent.core.agent_runtime.common.models import (
    CoordinatorDecision,
    CoordinatorMessageView,
)
from telegram_agent.core.agent_runtime.common.types import CoordinatorDecisionKind
from telegram_agent.core.agent_runtime.prompts.message_grouping import (
    build_message_grouping_prompts,
)
from telegram_agent.core.common.types import TelegramAttachmentType
from telegram_agent.core.llm_gateway.common.schemas import MessageGroupingResponse


def test_prompt_contains_current_message_latest_group_and_allowed_groups() -> None:
    latest_group = (
        CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=10,
            text="first topic",
            group_number=3,
        ),
        CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=20,
            text="sending a video",
            attachment_type=TelegramAttachmentType.VIDEO,
            group_number=3,
        ),
    )
    current = CoordinatorMessageView(
        ingress_message_id=uuid4(),
        message_id=30,
        reply_message_id=20,
        text="this one",
    )

    prompts = build_message_grouping_prompts(
        current=current,
        latest_group_messages=latest_group,
    )
    payload = json.loads(prompts.user_prompt)

    assert "Prefer new when continuity is weak" in prompts.system_prompt
    assert "Users do not need to say" in prompts.system_prompt
    assert payload["current_message"]["message_id"] == 30
    assert [
        item["message_id"]
        for item in payload["latest_group_messages_oldest_to_newest"]
    ] == [10, 20]
    assert payload["allowed_existing_group_numbers"] == [3]
    assert "recent_messages_oldest_to_newest" not in payload


def test_shared_decision_schema_requires_kind_and_nullable_group_number() -> None:
    assert CoordinatorDecision is MessageGroupingResponse
    decision = CoordinatorDecision.model_validate(
        {"kind": "existing", "group_number": 4}
    )
    assert decision.kind == CoordinatorDecisionKind.EXISTING
    with pytest.raises(ValidationError):
        CoordinatorDecision.model_validate(
            {"kind": "existing", "group_number": None}
        )
