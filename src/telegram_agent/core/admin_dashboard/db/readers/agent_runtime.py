"""SELECT-only queries against the agent-runtime database."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.admin_dashboard.db.mappings import agent_runtime as tables
from telegram_agent.core.admin_dashboard.services.view_models import (
    ConversationClaimRow,
    ConversationGroupRow,
    OutboxRow,
    RuntimeBatchRow,
    RuntimeMessageRow,
)


class AgentRuntimeReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_message(row: object) -> RuntimeMessageRow:
        return RuntimeMessageRow(
            id=row.id,  # type: ignore[attr-defined]
            batch_id=row.batch_id,  # type: ignore[attr-defined]
            ingress_message_id=row.ingress_message_id,  # type: ignore[attr-defined]
            chat_id=row.chat_id,  # type: ignore[attr-defined]
            telegram_user_id=row.telegram_user_id,  # type: ignore[attr-defined]
            message_id=row.message_id,  # type: ignore[attr-defined]
            reply_message_id=row.reply_message_id,  # type: ignore[attr-defined]
            text=row.text,  # type: ignore[attr-defined]
            attachment_ingress_id=row.attachment_ingress_id,  # type: ignore[attr-defined]
            attachment_type=row.attachment_type,  # type: ignore[attr-defined]
            attachment_status=row.attachment_status,  # type: ignore[attr-defined]
            attachment_file_id=row.attachment_file_id,  # type: ignore[attr-defined]
            attachment_file_unique_id=row.attachment_file_unique_id,  # type: ignore[attr-defined]
            group_id=row.group_id,  # type: ignore[attr-defined]
            coordination_status=row.coordination_status,  # type: ignore[attr-defined]
            status=row.status,  # type: ignore[attr-defined]
            intent=row.intent,  # type: ignore[attr-defined]
            coordinated_at=row.coordinated_at,  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
        )

    @staticmethod
    def _to_outbox(row: object) -> OutboxRow:
        return OutboxRow(
            id=row.id,  # type: ignore[attr-defined]
            event_type=row.event_type,  # type: ignore[attr-defined]
            status=row.status,  # type: ignore[attr-defined]
            attempt_count=row.attempt_count,  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
            published_at=row.published_at,  # type: ignore[attr-defined]
            available_at=row.available_at,  # type: ignore[attr-defined]
            locked_at=row.locked_at,  # type: ignore[attr-defined]
            locked_by=row.locked_by,  # type: ignore[attr-defined]
            last_error=row.last_error,  # type: ignore[attr-defined]
            idempotency_key=row.idempotency_key,  # type: ignore[attr-defined]
            payload=dict(row.payload or {}),  # type: ignore[attr-defined]
            chat_id=row.chat_id,  # type: ignore[attr-defined]
            runtime_message_id=row.runtime_message_id,  # type: ignore[attr-defined]
            message_id=row.message_id,  # type: ignore[attr-defined]
        )

    async def get_message_by_ingress_id(
        self,
        ingress_message_id: UUID,
    ) -> RuntimeMessageRow | None:
        tbl = tables.runtime_messages
        result = await self._session.execute(
            select(tbl).where(tbl.c.ingress_message_id == ingress_message_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return self._to_message(row)

    async def list_messages_by_group_id(
        self,
        group_id: UUID,
    ) -> list[RuntimeMessageRow]:
        """All runtime messages assigned to a conversation group, in Telegram order."""
        tbl = tables.runtime_messages
        result = await self._session.execute(
            select(tbl)
            .where(tbl.c.group_id == group_id)
            .order_by(tbl.c.message_id.asc(), tbl.c.created_at.asc(), tbl.c.id.asc())
        )
        return [self._to_message(row) for row in result]

    async def get_batch(self, batch_id: UUID) -> RuntimeBatchRow | None:
        tbl = tables.runtime_batches
        result = await self._session.execute(select(tbl).where(tbl.c.id == batch_id))
        row = result.one_or_none()
        if row is None:
            return None
        return RuntimeBatchRow(
            id=row.id,
            chat_id=row.chat_id,
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
        )

    async def get_group(self, group_id: UUID) -> ConversationGroupRow | None:
        tbl = tables.conversation_groups
        result = await self._session.execute(select(tbl).where(tbl.c.id == group_id))
        row = result.one_or_none()
        if row is None:
            return None
        return ConversationGroupRow(
            id=row.id,
            chat_id=row.chat_id,
            group_number=row.group_number,
            created_at=row.created_at,
        )

    async def get_outbox_for_message(self, runtime_message_id: UUID) -> OutboxRow | None:
        events = await self.list_outbox_for_message(runtime_message_id)
        if not events:
            return None
        for event in events:
            if "pending_coordination" in event.event_type:
                return event
        return events[0]

    async def list_outbox_for_message(
        self,
        runtime_message_id: UUID,
    ) -> list[OutboxRow]:
        tbl = tables.coordination_outbox_events
        result = await self._session.execute(
            select(tbl)
            .where(tbl.c.runtime_message_id == runtime_message_id)
            .order_by(tbl.c.created_at.asc(), tbl.c.id.asc())
        )
        return [self._to_outbox(row) for row in result]

    async def get_claim(self, chat_id: int) -> ConversationClaimRow | None:
        tbl = tables.conversation_claims
        result = await self._session.execute(
            select(tbl).where(tbl.c.chat_id == chat_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return ConversationClaimRow(
            chat_id=row.chat_id,
            status=row.status,
            claim_token=row.claim_token,
            locked_at=row.locked_at,
            locked_by=row.locked_by,
            available_at=row.available_at,
            updated_at=row.updated_at,
        )

    async def list_pipeline_status_by_ingress_ids(
        self,
        ingress_ids: list[UUID],
    ) -> dict[UUID, dict[str, str | None]]:
        """Return pipeline + coordination status per ingress message id."""
        if not ingress_ids:
            return {}
        tbl = tables.runtime_messages
        result = await self._session.execute(
            select(
                tbl.c.ingress_message_id,
                tbl.c.status,
                tbl.c.coordination_status,
                tbl.c.intent,
            ).where(tbl.c.ingress_message_id.in_(ingress_ids))
        )
        return {
            row.ingress_message_id: {
                "status": row.status,
                "coordination_status": row.coordination_status,
                "intent": row.intent,
            }
            for row in result
        }

    async def list_coordination_status_by_ingress_ids(
        self,
        ingress_ids: list[UUID],
    ) -> dict[UUID, str]:
        """Backward-compatible map of ingress id → coordination_status."""
        data = await self.list_pipeline_status_by_ingress_ids(ingress_ids)
        return {
            ingress_id: str(values["coordination_status"] or "")
            for ingress_id, values in data.items()
        }
