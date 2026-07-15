"""SELECT-only queries against the telegram-auth database."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from telegram_agent.core.admin_dashboard.db.mappings import telegram_auth as tables
from telegram_agent.core.admin_dashboard.services.view_models import AuthUserRow


class AuthReader:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> AuthUserRow | None:
        tbl = tables.telegram_users
        result = await self._session.execute(
            select(tbl).where(tbl.c.telegram_user_id == telegram_user_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        return AuthUserRow(
            id=row.id,
            telegram_user_id=row.telegram_user_id,
            chat_id=row.chat_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            is_active=row.is_active,
            last_seen_at=row.last_seen_at,
        )
