from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.db.models.content_processing import TelegramSource


class SyncSqlAlchemyTelegramSourceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_by_job_id(self, job_id: UUID) -> list[TelegramSource]:
        return list(
            self._session.scalars(
                select(TelegramSource).where(TelegramSource.job_id == job_id)
            ).all()
        )

    def list_by_ingress_message_id(
        self,
        ingress_message_id: UUID,
    ) -> list[TelegramSource]:
        return list(
            self._session.scalars(
                select(TelegramSource).where(
                    TelegramSource.ingress_message_id == ingress_message_id
                )
            ).all()
        )
