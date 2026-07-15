from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import insert
from sqlalchemy.engine import make_url

from telegram_agent.core.admin_dashboard_v2.api.v1.fastapi_app import create_app
from telegram_agent.core.admin_dashboard_v2.common.exceptions import DataSourceUnavailableError
from telegram_agent.core.admin_dashboard_v2.common.types import MessageListFilters
from telegram_agent.core.admin_dashboard_v2.db.readers.agent_runtime import AgentRuntimeReader
from telegram_agent.core.admin_dashboard_v2.db.readers.content_processing import ContentProcessingReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_auth import TelegramAuthReader
from telegram_agent.core.admin_dashboard_v2.db.readers.telegram_ingress import TelegramIngressReader
from telegram_agent.core.admin_dashboard_v2.db.tables.agent_runtime import (
    conversation_groups,
    coordination_outbox_events,
    runtime_batches,
    runtime_messages,
)
from telegram_agent.core.admin_dashboard_v2.db.tables.content_processing import (
    jobs,
    media_assets,
    outbox_events,
    telegram_sources,
    transcript_segments,
    transcripts,
)
from telegram_agent.core.admin_dashboard_v2.db.tables.telegram_auth import telegram_users
from telegram_agent.core.admin_dashboard_v2.db.tables.telegram_ingress import (
    attachments,
    conversation_outbox_events,
    user_messages,
)
from telegram_agent.core.admin_dashboard_v2.services.message_listing import MessageListingService
from telegram_agent.core.admin_dashboard_v2.services.message_trace import MessageTraceQueryService
from tests.admin_dashboard_v2.conftest import build_settings


pytestmark = pytest.mark.asyncio


async def test_listing_and_trace_correlate_all_databases(
    auth_engine,
    ingress_engine,
    content_engine,
    agent_runtime_engine,
    dashboard_databases,
    dashboard_settings,
) -> None:
    ids = await _seed_complete_voice_trace(
        auth_engine,
        ingress_engine,
        content_engine,
        agent_runtime_engine,
    )
    ingress = TelegramIngressReader(dashboard_databases)
    content = ContentProcessingReader(dashboard_databases)
    runtime = AgentRuntimeReader(dashboard_databases)
    auth = TelegramAuthReader(dashboard_databases)
    listing = MessageListingService(
        ingress=ingress,
        content=content,
        runtime=runtime,
        auth=auth,
        settings=dashboard_settings,
    )
    page = await listing.list_messages(
        filters=MessageListFilters(chat_id=7001),
        cursor_value=None,
        page_size=10,
    )
    assert len(page.items) == 1
    assert page.items[0].ingress_message_id == ids["ingress_message_id"]
    assert page.items[0].overall_status == "coordinated"
    assert page.items[0].current_user_label == "Ada Operator"
    assert page.items[0].content_statuses == ("completed",)

    trace = await MessageTraceQueryService(
        ingress=ingress,
        content=content,
        runtime=runtime,
        auth=auth,
        settings=dashboard_settings,
    ).get_trace(ids["ingress_message_id"])
    assert trace.overall_status == "coordinated"
    assert set(trace.available_tabs) == {
        "telegram_ingress",
        "content_processing",
        "agent_runtime",
        "telegram_auth",
    }
    attempt = trace.content_processing.data["attempts"][0]
    assert attempt["canonical_ingress_request"] is True
    assert attempt["telegram_file_id"] != "telegram-secret-file-id"
    assert attempt["assets"][0]["local_path"] == "<masked>/voice.ogg"
    stage_by_key = {stage.key: stage for stage in trace.lifecycle}
    assert stage_by_key["transcription"].status.value == "completed"
    assert stage_by_key["agent_execution"].status.value == "not_implemented"

    app = create_app(dashboard_settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://dashboard.test",
        ) as client:
            response = await client.get(
                f"/messages/{ids['ingress_message_id']}",
                auth=("operator", "dashboard-test-password"),
            )
    assert response.status_code == 200
    assert "voice transcript" in response.text
    assert "Content processing" in response.text
    assert "Agent runtime" in response.text


async def test_read_database_connection_rejects_writes(
    dashboard_databases,
) -> None:
    with pytest.raises(DataSourceUnavailableError):
        async with dashboard_databases.connection("telegram_ingress") as connection:
            await connection.execute(
                insert(user_messages).values(
                    id=uuid4(),
                    telegram_user_id=1,
                    chat_id=1,
                    message_id=1,
                    conversation_status="pending",
                )
            )


async def test_keyset_pagination_does_not_skip_prefetched_rows(
    ingress_engine,
    dashboard_databases,
    dashboard_settings,
) -> None:
    now = datetime.now(timezone.utc)
    expected_ids = [uuid4(), uuid4(), uuid4()]
    async with ingress_engine.begin() as connection:
        for index, ingress_message_id in enumerate(expected_ids):
            await connection.execute(
                insert(user_messages).values(
                    id=ingress_message_id,
                    telegram_user_id=100 + index,
                    chat_id=8001,
                    message_id=300 - index,
                    text=f"message {index}",
                    conversation_status="pending",
                    created_at=now - timedelta(seconds=index),
                )
            )

    listing = MessageListingService(
        ingress=TelegramIngressReader(dashboard_databases),
        content=ContentProcessingReader(dashboard_databases),
        runtime=AgentRuntimeReader(dashboard_databases),
        auth=TelegramAuthReader(dashboard_databases),
        settings=dashboard_settings,
    )
    cursor = None
    observed_ids: list[UUID] = []
    for _ in range(3):
        page = await listing.list_messages(
            filters=MessageListFilters(chat_id=8001),
            cursor_value=cursor,
            page_size=1,
        )
        assert len(page.items) == 1
        observed_ids.append(page.items[0].ingress_message_id)
        cursor = page.next_cursor
        assert cursor is not None

    assert observed_ids == expected_ids


async def test_invalid_database_password_renders_partial_page(
    database_urls: dict[str, str],
) -> None:
    invalid_urls = dict(database_urls)
    invalid_urls["ingress"] = make_url(database_urls["ingress"]).set(
        password="deliberately-invalid-dashboard-password"
    ).render_as_string(hide_password=False)
    settings = build_settings(invalid_urls)
    app = create_app(settings)

    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://dashboard.test",
        ) as client:
            response = await client.get(
                "/messages",
                auth=("operator", "dashboard-test-password"),
            )

    assert response.status_code == 200
    assert "Telegram Ingress: Database query unavailable" in response.text
    assert "deliberately-invalid-dashboard-password" not in response.text


async def _seed_complete_voice_trace(
    auth_engine,
    ingress_engine,
    content_engine,
    agent_runtime_engine,
) -> dict[str, UUID]:
    now = datetime.now(timezone.utc)
    ingress_message_id = uuid4()
    ingress_attachment_id = uuid4()
    ingress_outbox_id = uuid4()
    job_id = uuid4()
    source_id = uuid4()
    asset_id = uuid4()
    transcript_id = uuid4()
    runtime_message_id = uuid4()
    group_id = uuid4()
    canonical_key = f"telegram-ingress:process-attachment:voice:{ingress_attachment_id}:v1"

    async with auth_engine.begin() as connection:
        await connection.execute(
            insert(telegram_users).values(
                telegram_user_id=9001,
                chat_id=7001,
                username="ada",
                first_name="Ada",
                last_name="Operator",
                is_bot=False,
                language_code="en",
                is_active=True,
                verified_at=now,
                last_seen_at=now,
            )
        )
    async with ingress_engine.begin() as connection:
        await connection.execute(
            insert(conversation_outbox_events).values(
                id=ingress_outbox_id,
                event_type="telegram_ingress.conversation_messages.enqueued",
                chat_id=7001,
                first_message_id=42,
                idempotency_key="ingress-batch-key",
                payload={"messages": [{"ingress_message_id": str(ingress_message_id), "file_id": "must-mask"}]},
                status="published",
                attempt_count=1,
                available_at=now,
                created_at=now,
                published_at=now,
            )
        )
        await connection.execute(
            insert(user_messages).values(
                id=ingress_message_id,
                telegram_user_id=9001,
                chat_id=7001,
                message_id=42,
                update_id=4200,
                reply_message_id=None,
                text="voice transcript",
                conversation_status="dispatched",
                dispatch_event_id=ingress_outbox_id,
                created_at=now,
            )
        )
        await connection.execute(
            insert(attachments).values(
                id=ingress_attachment_id,
                user_message_id=ingress_message_id,
                file_id="telegram-secret-file-id",
                file_unique_id="stable-file-id",
                type="voice",
                status="ready",
                created_at=now,
            )
        )
    async with content_engine.begin() as connection:
        await connection.execute(
            insert(jobs).values(
                id=job_id,
                kind="telegram attachment",
                status="completed",
                idempotency_key=canonical_key,
                error_message=None,
                callback_required=True,
                created_at=now,
                updated_at=now,
            )
        )
        await connection.execute(
            insert(telegram_sources).values(
                id=source_id,
                job_id=job_id,
                ingress_message_id=ingress_message_id,
                ingress_attachment_id=ingress_attachment_id,
                telegram_user_id=9001,
                telegram_file_id="telegram-secret-file-id",
                telegram_file_unique_id="stable-file-id",
                attachment_type="voice",
            )
        )
        await connection.execute(
            insert(media_assets).values(
                id=asset_id,
                job_id=job_id,
                role="source",
                parent_asset_id=None,
                local_path="/private/media/voice.ogg",
                media_type="voice",
                mime_type="audio/ogg",
                duration_ms=1000,
                size_bytes=100,
            )
        )
        await connection.execute(
            insert(transcripts).values(
                id=transcript_id,
                job_id=job_id,
                text="voice transcript",
                language="en",
                language_probability=0.99,
                duration_ms=1000,
            )
        )
        await connection.execute(
            insert(transcript_segments).values(
                id=uuid4(), transcript_id=transcript_id, segment_index=0,
                start_ms=0, end_ms=1000, text="voice transcript", language="en",
            )
        )
        for event_type in (
            "content_processing.job.ready",
            "content_processing.media.ready_for_transcription",
            "content_processing.job.finished",
        ):
            await connection.execute(
                insert(outbox_events).values(
                    id=uuid4(), event_type=event_type, job_id=job_id,
                    idempotency_key=f"{event_type}:{job_id}", payload={}, status="published",
                    attempt_count=0, available_at=now, created_at=now, published_at=now,
                )
            )
    async with agent_runtime_engine.begin() as connection:
        await connection.execute(
            insert(runtime_batches).values(
                id=ingress_outbox_id,
                chat_id=7001,
                idempotency_key="ingress-batch-key",
                created_at=now,
            )
        )
        await connection.execute(
            insert(conversation_groups).values(
                id=group_id, chat_id=7001, group_number=1, created_at=now
            )
        )
        await connection.execute(
            insert(runtime_messages).values(
                id=runtime_message_id,
                batch_id=ingress_outbox_id,
                ingress_message_id=ingress_message_id,
                chat_id=7001,
                telegram_user_id=9001,
                message_id=42,
                text="voice transcript",
                attachment_ingress_id=ingress_attachment_id,
                attachment_type="voice",
                attachment_status="ready",
                attachment_file_id="telegram-secret-file-id",
                attachment_file_unique_id="stable-file-id",
                group_id=group_id,
                coordination_status="grouped",
                coordinated_at=now,
                created_at=now,
            )
        )
        await connection.execute(
            insert(coordination_outbox_events).values(
                id=uuid4(), event_type="agent_runtime.message.pending_coordination",
                chat_id=7001, runtime_message_id=runtime_message_id, message_id=42,
                idempotency_key=f"agent_runtime:coordinate:{ingress_message_id}:v1",
                payload={"ingress_message_id": str(ingress_message_id)},
                status="published", attempt_count=0, available_at=now,
                created_at=now, published_at=now,
            )
        )
    return {"ingress_message_id": ingress_message_id}
