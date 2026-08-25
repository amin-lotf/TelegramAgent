from __future__ import annotations

from types import TracebackType

from sqlalchemy.orm import Session

from telegram_agent.core.content_processing.db.repositories.sync_download_request import (
    SyncSqlAlchemyDownloadRequestRepository,
)
from telegram_agent.core.content_processing.db.repositories.sync_dubbing import (
    SyncSqlAlchemyDubbingRepository,
)
from telegram_agent.core.content_processing.db.repositories.sync_job import SyncSqlAlchemyJobRepository
from telegram_agent.core.content_processing.db.repositories.sync_job_expectation import (
    SyncSqlAlchemyJobExpectationRepository,
)
from telegram_agent.core.content_processing.db.repositories.sync_media_asset import SyncSqlAlchemyMediaAssetRepository
from telegram_agent.core.content_processing.db.repositories.sync_outbox import SyncSqlAlchemyOutboxRepository
from telegram_agent.core.content_processing.db.repositories.sync_subtitle_translation import (
    SyncSqlAlchemySubtitleTranslationRepository,
)
from telegram_agent.core.content_processing.db.repositories.sync_telegram_source import SyncSqlAlchemyTelegramSourceRepository
from telegram_agent.core.content_processing.db.repositories.sync_transcript import SyncSqlAlchemyTranscriptRepository


class SyncSqlAlchemyContentProcessingUnitOfWork:
    def __init__(self, session: Session):
        self._session = session
        self.jobs = SyncSqlAlchemyJobRepository(session)
        self.job_expectations = SyncSqlAlchemyJobExpectationRepository(session)
        self.media_assets = SyncSqlAlchemyMediaAssetRepository(session)
        self.telegram_sources = SyncSqlAlchemyTelegramSourceRepository(session)
        self.transcripts = SyncSqlAlchemyTranscriptRepository(session)
        self.download_requests = SyncSqlAlchemyDownloadRequestRepository(session)
        self.dubbing = SyncSqlAlchemyDubbingRepository(session)
        self.subtitle_translations = SyncSqlAlchemySubtitleTranslationRepository(session)
        self.outbox_events = SyncSqlAlchemyOutboxRepository(session)

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()

    def flush(self) -> None:
        self._session.flush()

    def __enter__(self) -> "SyncSqlAlchemyContentProcessingUnitOfWork":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type:
            self.rollback()
        else:
            self.commit()
