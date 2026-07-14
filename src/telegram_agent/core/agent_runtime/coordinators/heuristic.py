from __future__ import annotations

import re
from typing import Sequence

from telegram_agent.core.agent_runtime.common.types import CoordinatorDecisionKind
from telegram_agent.core.agent_runtime.coordinators.base import (
    CoordinatorDecision,
    CoordinatorMessageView,
    MessageGroupCoordinator,
)

_VAGUE_ONLY = re.compile(
    r"^(it|this|that|those|these|same|continue|yes|no|ok|okay|sure|what\??|huh\??)$",
    re.IGNORECASE,
)


class HeuristicMessageGroupCoordinator:
    """Deterministic non-LLM coordinator used until a vLLM adapter is wired."""

    def assign_group(
        self,
        *,
        current: CoordinatorMessageView,
        recent_window: Sequence[CoordinatorMessageView],
    ) -> CoordinatorDecision:
        if not recent_window:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)

        if current.reply_message_id is not None:
            for previous in recent_window:
                if (
                    previous.message_id == current.reply_message_id
                    and previous.group_number is not None
                ):
                    return CoordinatorDecision(
                        kind=CoordinatorDecisionKind.EXISTING,
                        group_number=previous.group_number,
                    )

        last = recent_window[-1]
        attachment_only = current.text is None and current.attachment_type is not None
        if attachment_only and last.group_number is not None:
            return CoordinatorDecision(
                kind=CoordinatorDecisionKind.EXISTING,
                group_number=last.group_number,
            )

        if attachment_only and last.group_number is None:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)

        text = (current.text or "").strip()
        if text and _VAGUE_ONLY.match(text) and current.reply_message_id is None:
            return CoordinatorDecision(kind=CoordinatorDecisionKind.VAGUE)

        if last.group_number is not None:
            return CoordinatorDecision(
                kind=CoordinatorDecisionKind.EXISTING,
                group_number=last.group_number,
            )

        return CoordinatorDecision(kind=CoordinatorDecisionKind.NEW)


def default_message_group_coordinator() -> MessageGroupCoordinator:
    return HeuristicMessageGroupCoordinator()
