from __future__ import annotations

from collections.abc import Collection
from typing import Any

from sqlalchemy import select

from telegram_agent.core.admin_dashboard_v2.db.engines import ReadDatabaseManager
from telegram_agent.core.admin_dashboard_v2.db.tables.telegram_auth import telegram_users


def _mapping(row: Any) -> dict[str, Any]:
    return dict(row._mapping)


class TelegramAuthReader:
    source = "telegram_auth"

    def __init__(self, databases: ReadDatabaseManager) -> None:
        self._databases = databases

    async def users_by_telegram_ids(
        self, telegram_user_ids: Collection[int]
    ) -> dict[int, dict[str, Any]]:
        if not telegram_user_ids:
            return {}
        async with self._databases.connection(self.source) as connection:
            rows = (
                await connection.execute(
                    select(telegram_users).where(
                        telegram_users.c.telegram_user_id.in_(telegram_user_ids)
                    )
                )
            ).all()
        return {row.telegram_user_id: _mapping(row) for row in rows}

    async def get_by_telegram_user_id(self, telegram_user_id: int) -> dict[str, Any] | None:
        async with self._databases.connection(self.source) as connection:
            row = (
                await connection.execute(
                    select(telegram_users).where(
                        telegram_users.c.telegram_user_id == telegram_user_id
                    )
                )
            ).one_or_none()
        return _mapping(row) if row is not None else None
