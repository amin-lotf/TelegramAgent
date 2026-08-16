from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from telegram_agent.core.admin_dashboard_v2.common.types import (
    DataSourceStatus,
    SourceResult,
    StageStatus,
)
from telegram_agent.core.admin_dashboard_v2.services.timeline import (
    build_lifecycle_and_timeline,
)


def test_download_timeline_uses_agent_result_for_traced_request() -> None:
    request_id = uuid4()
    matching_agent_id = uuid4()
    now = datetime.now(timezone.utc)
    ingress = SourceResult[dict](
        source="telegram_ingress",
        status=DataSourceStatus.AVAILABLE,
        data={"message": {"id": request_id, "created_at": now}},
    )
    content = SourceResult[dict](
        source="content_processing",
        status=DataSourceStatus.RECORD_NOT_FOUND,
        data=None,
    )
    runtime = SourceResult[dict](
        source="agent_runtime",
        status=DataSourceStatus.AVAILABLE,
        data={
            "message": {
                "id": uuid4(),
                "ingress_message_id": request_id,
                "coordination_status": "grouped",
                "status": "coordinated",
                "intent": None,
                "created_at": now,
                "coordinated_at": now,
            },
            "agent_messages": [
                {
                    "id": uuid4(),
                    "ingress_message_id": uuid4(),
                    "role": "download_agent",
                    "created_at": now,
                },
                {
                    "id": matching_agent_id,
                    "ingress_message_id": request_id,
                    "role": "download_agent",
                    "created_at": now,
                },
            ],
            "outbox_events": [],
        },
    )

    stages, events = build_lifecycle_and_timeline(ingress, content, runtime)

    download_stage = next(stage for stage in stages if stage.key == "download_handler")
    download_event = next(event for event in events if event.key == "download_handler")
    assert download_stage.status == StageStatus.COMPLETED
    assert download_event.record_id == str(matching_agent_id)
