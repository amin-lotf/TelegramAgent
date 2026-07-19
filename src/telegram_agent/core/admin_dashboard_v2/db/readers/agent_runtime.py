from __future__ import annotations

from collections.abc import Collection
from typing import Any
from uuid import UUID

from sqlalchemy import select

from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.db.tables.agent_runtime import (
    agent_messages,
    conversation_claims,
    conversation_groups,
    coordination_outbox_events,
    runtime_batches,
    runtime_messages,
)


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


class AgentRuntimeReader:
    source = "agent_runtime"

    def __init__(self, databases: ReadDatabaseManager) -> None:
        self._databases = databases

    async def statuses_by_ingress_ids(
        self, ingress_message_ids: Collection[UUID]
    ) -> dict[UUID, dict[str, Any]]:
        if not ingress_message_ids:
            return {}
        statement = (
            select(
                runtime_messages.c.ingress_message_id,
                runtime_messages.c.id.label("runtime_message_id"),
                runtime_messages.c.coordination_status,
                runtime_messages.c.status,
                runtime_messages.c.intent,
                runtime_messages.c.group_id,
                runtime_messages.c.created_at,
                runtime_messages.c.coordinated_at,
            )
            .where(runtime_messages.c.ingress_message_id.in_(ingress_message_ids))
        )
        async with self._databases.connection(self.source) as connection:
            rows = (await connection.execute(statement)).all()
            result: dict[UUID, dict[str, Any]] = {
                row.ingress_message_id: _mapping(row) for row in rows
            }
            if not result:
                return {}
            runtime_ids = [item["runtime_message_id"] for item in result.values()]
            outbox_rows = (
                await connection.execute(
                    select(coordination_outbox_events).where(
                        coordination_outbox_events.c.runtime_message_id.in_(runtime_ids)
                    )
                )
            ).all()

        outbox_by_message: dict[UUID, list[dict[str, Any]]] = {}
        for row in outbox_rows:
            mapped = _mapping(row)
            outbox_by_message.setdefault(mapped["runtime_message_id"], []).append(mapped)

        for item in result.values():
            events = outbox_by_message.get(item["runtime_message_id"], [])
            item["outbox_events"] = events
            failed = next((e for e in events if e.get("status") == "failed"), None)
            preferred = failed or next(
                (e for e in events if "pending_coordination" in str(e.get("event_type"))),
                events[0] if events else None,
            )
            item["outbox_status"] = preferred.get("status") if preferred else None
            item["attempt_count"] = preferred.get("attempt_count") if preferred else None
            item["last_error"] = preferred.get("last_error") if preferred else None
        return result

    async def resolve_ingress_ids_by_group_id(self, group_id: UUID) -> set[UUID]:
        async with self._databases.connection(self.source) as connection:
            values = (
                await connection.execute(
                    select(runtime_messages.c.ingress_message_id).where(
                        runtime_messages.c.group_id == group_id
                    )
                )
            ).scalars()
            return set(values)

    async def get_trace(self, ingress_message_id: UUID, *, sibling_limit: int) -> dict[str, Any] | None:
        statement = (
            select(
                *runtime_messages.c,
                runtime_batches.c.chat_id.label("batch_chat_id"),
                runtime_batches.c.idempotency_key.label("batch_idempotency_key"),
                runtime_batches.c.created_at.label("batch_created_at"),
                conversation_groups.c.group_number,
                conversation_groups.c.created_at.label("group_created_at"),
            )
            .join(runtime_batches, runtime_batches.c.id == runtime_messages.c.batch_id)
            .outerjoin(
                conversation_groups,
                conversation_groups.c.id == runtime_messages.c.group_id,
            )
            .where(runtime_messages.c.ingress_message_id == ingress_message_id)
        )
        async with self._databases.connection(self.source) as connection:
            row = (await connection.execute(statement)).one_or_none()
            if row is None:
                return None
            flattened = _mapping(row)
            runtime_message_id = flattened["id"]
            outbox_rows = (
                await connection.execute(
                    select(coordination_outbox_events)
                    .where(
                        coordination_outbox_events.c.runtime_message_id
                        == runtime_message_id
                    )
                    .order_by(
                        coordination_outbox_events.c.created_at.asc(),
                        coordination_outbox_events.c.id.asc(),
                    )
                )
            ).all()
            claim_row = (
                await connection.execute(
                    select(conversation_claims).where(
                        conversation_claims.c.chat_id == flattened["chat_id"]
                    )
                )
            ).one_or_none()
            siblings: list[dict[str, Any]] = []
            agent_message_rows: list[Any] = []
            if flattened["group_id"] is not None:
                sibling_rows = (
                    await connection.execute(
                        select(
                            runtime_messages.c.id,
                            runtime_messages.c.ingress_message_id,
                            runtime_messages.c.message_id,
                            runtime_messages.c.text,
                            runtime_messages.c.coordination_status,
                            runtime_messages.c.status,
                            runtime_messages.c.intent,
                            runtime_messages.c.created_at,
                            runtime_messages.c.coordinated_at,
                        )
                        .where(runtime_messages.c.group_id == flattened["group_id"])
                        .order_by(runtime_messages.c.message_id, runtime_messages.c.id)
                        .limit(sibling_limit)
                    )
                ).all()
                siblings = [_mapping(item) for item in sibling_rows]
                agent_message_rows = (
                    await connection.execute(
                        select(agent_messages)
                        .where(agent_messages.c.group_id == flattened["group_id"])
                        .order_by(agent_messages.c.created_at.asc(), agent_messages.c.id.asc())
                    )
                ).all()

        batch = {
            "id": flattened["batch_id"],
            "chat_id": flattened.pop("batch_chat_id"),
            "idempotency_key": flattened.pop("batch_idempotency_key"),
            "created_at": flattened.pop("batch_created_at"),
        }
        group = None
        if flattened["group_id"] is not None:
            group = {
                "id": flattened["group_id"],
                "chat_id": flattened["chat_id"],
                "group_number": flattened.pop("group_number"),
                "created_at": flattened.pop("group_created_at"),
            }
        else:
            flattened.pop("group_number", None)
            flattened.pop("group_created_at", None)

        outbox_events = [_mapping(item) for item in outbox_rows]
        primary_outbox = next(
            (
                event
                for event in outbox_events
                if "pending_coordination" in str(event.get("event_type"))
            ),
            outbox_events[0] if outbox_events else None,
        )
        return {
            "message": flattened,
            "batch": batch,
            "group": group,
            "claim": _mapping(claim_row) if claim_row is not None else None,
            "outbox": primary_outbox,
            "outbox_events": outbox_events,
            "agent_messages": [_mapping(item) for item in agent_message_rows],
            "group_siblings": siblings,
            "group_siblings_truncated": len(siblings) >= sibling_limit,
        }
