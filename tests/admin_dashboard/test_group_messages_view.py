from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard.services.view_models import (
    AgentRuntimeView,
    RuntimeMessageRow,
)


def _msg(*, group_id, message_id: int) -> RuntimeMessageRow:
    return RuntimeMessageRow(
        id=uuid4(),
        batch_id=uuid4(),
        ingress_message_id=uuid4(),
        chat_id=1,
        telegram_user_id=1,
        message_id=message_id,
        reply_message_id=None,
        text=f"msg {message_id}",
        attachment_ingress_id=None,
        attachment_type=None,
        attachment_status=None,
        attachment_file_id=None,
        attachment_file_unique_id=None,
        group_id=group_id,
        coordination_status="grouped",
        status="classified",
        intent="conversation",
        coordinated_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


def test_agent_runtime_view_carries_group_messages() -> None:
    group_id = uuid4()
    current = _msg(group_id=group_id, message_id=2)
    peers = (
        _msg(group_id=group_id, message_id=1),
        current,
        _msg(group_id=group_id, message_id=3),
    )
    view = AgentRuntimeView(
        message=current,
        batch=None,
        group=None,
        outbox=None,
        claim=None,
        group_messages=peers,
    )
    assert len(view.group_messages) == 3
    assert view.group_messages[1].id == current.id
