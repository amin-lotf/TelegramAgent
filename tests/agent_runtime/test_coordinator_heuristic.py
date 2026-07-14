from uuid import uuid4

from telegram_agent.core.agent_runtime.common.types import CoordinatorDecisionKind
from telegram_agent.core.agent_runtime.coordinators.base import CoordinatorMessageView
from telegram_agent.core.agent_runtime.coordinators.heuristic import (
    HeuristicMessageGroupCoordinator,
)
from telegram_agent.core.common.types import TelegramAttachmentType


def test_new_when_window_empty() -> None:
    decision = HeuristicMessageGroupCoordinator().assign_group(
        current=CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=1,
            text="hello",
        ),
        recent_window=(),
    )
    assert decision.kind == CoordinatorDecisionKind.NEW


def test_reply_maps_to_existing_group_number() -> None:
    previous = CoordinatorMessageView(
        ingress_message_id=uuid4(),
        message_id=10,
        text="question",
        group_number=1,
    )
    decision = HeuristicMessageGroupCoordinator().assign_group(
        current=CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=11,
            reply_message_id=10,
            text="answer",
        ),
        recent_window=(previous,),
    )
    assert decision.kind == CoordinatorDecisionKind.EXISTING
    assert decision.group_number == 1


def test_attachment_follows_previous_group() -> None:
    previous = CoordinatorMessageView(
        ingress_message_id=uuid4(),
        message_id=10,
        text="sending video",
        group_number=2,
    )
    decision = HeuristicMessageGroupCoordinator().assign_group(
        current=CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=11,
            attachment_type=TelegramAttachmentType.VIDEO,
        ),
        recent_window=(previous,),
    )
    assert decision.kind == CoordinatorDecisionKind.EXISTING
    assert decision.group_number == 2


def test_vague_anaphora() -> None:
    previous = CoordinatorMessageView(
        ingress_message_id=uuid4(),
        message_id=10,
        text="long context",
        group_number=1,
    )
    decision = HeuristicMessageGroupCoordinator().assign_group(
        current=CoordinatorMessageView(
            ingress_message_id=uuid4(),
            message_id=11,
            text="this",
        ),
        recent_window=(previous,),
    )
    assert decision.kind == CoordinatorDecisionKind.VAGUE
