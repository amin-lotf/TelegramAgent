from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from telegram_agent.core.content_processing.common.commands import (
    RecordSegmentEmotionsCommand,
    RecordTranscriptCommand,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    Transcript,
    TranscriptSegment,
)

logger = logging.getLogger(__name__)


class SyncSqlAlchemyTranscriptRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_job_id(self, job_id: UUID) -> Transcript | None:
        return self._session.scalar(
            select(Transcript).where(Transcript.job_id == job_id)
        )

    def get_by_job_id_with_segments(self, job_id: UUID) -> Transcript | None:
        return self._session.scalar(
            select(Transcript)
            .where(Transcript.job_id == job_id)
            .options(selectinload(Transcript.segments))
        )

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

    def update_segment_emotions(self, command: RecordSegmentEmotionsCommand) -> bool:
        transcript = self.get_by_job_id_with_segments(command.job_id)
        if transcript is None:
            return False

        segments_by_index = {
            segment.segment_index: segment for segment in transcript.segments
        }
        for update in command.segments:
            segment = segments_by_index.get(update.segment_index)
            if segment is None:
                return False
            segment.emotion = update.emotion
            segment.audio_events = (
                list(update.audio_events) if update.audio_events is not None else None
            )
        self._session.flush()
        return True
