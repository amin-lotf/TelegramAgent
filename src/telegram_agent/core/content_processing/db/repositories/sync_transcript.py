from __future__ import annotations

from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
import  logging
from telegram_agent.core.content_processing.common.commands import RecordTranscriptCommand
from telegram_agent.core.content_processing.db.models.content_processing import Transcript, TranscriptSegment

logger = logging.getLogger(__name__)

class SyncSqlAlchemyTranscriptRepository:
    def get_by_job_id(self, job_id: UUID) -> Transcript | None:
        return self._session.scalar(select(Transcript).where(Transcript.job_id == job_id))

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, command: RecordTranscriptCommand) -> bool:
        if self._session.scalar(select(Transcript.id).where(Transcript.job_id == command.job_id)) is not None:
            return True
        transcript = Transcript(
            job_id=command.job_id,
            text=command.text,
            language=command.language,
            language_probability=command.language_probability,
            duration_ms=command.duration_ms,
        )
        self._session.add(transcript)
        self._session.flush()
        for segment in command.segments:
            self._session.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    segment_index=segment.segment_index,
                    start_ms=segment.start_ms,
                    end_ms=segment.end_ms,
                    text=segment.text,
                    language=segment.language,
                    language_probability=segment.language_probability,
                    speaker=segment.speaker,
                    speaker_confidence=segment.speaker_confidence,
                )
            )
        self._session.flush()
        return True
