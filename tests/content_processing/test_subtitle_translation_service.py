from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from telegram_agent.core.common.exceptions import PermanentContentProcessingError
from telegram_agent.core.content_processing.clients.llm_gateway import (
    LlmGatewayGeneration,
    LlmGatewayTokenUsage,
)
from telegram_agent.core.content_processing.common.settings import settings
from telegram_agent.core.content_processing.common.types import (
    JobKind,
    JobStatus,
    SubtitleTranslationStatus,
    TranslationBatchStatus,
)
from telegram_agent.core.content_processing.db.models.content_processing import (
    Job,
    SubtitleTranslation,
    Transcript,
    TranscriptSegment,
    TranslatedSegment,
    TranslationBatch,
)
from telegram_agent.core.content_processing.services.sync_subtitle_translation_service import (
    SyncSubtitleTranslationService,
)


class FakeLlmClient:
    def __init__(self) -> None:
        self.glossary_calls = 0
        self.translate_calls = 0
        self.translate_prompts: list[str] = []

    def extract_glossary(self, *, system_prompt: str, user_prompt: str) -> LlmGatewayGeneration:
        self.glossary_calls += 1
        return LlmGatewayGeneration(
            request_id="g1",
            output={
                "entries": [
                    {
                        "source_term": "Alice",
                        "preferred_translation": "آلیس",
                        "category": "person",
                        "expansion": None,
                        "notes": None,
                    }
                ],
                "tone_guidance": "Natural spoken tone.",
            },
            provider="stub",
            model="stub-model",
            provider_request_id="prov-g",
            usage=LlmGatewayTokenUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    def translate_subtitle_batch(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
    ) -> LlmGatewayGeneration:
        self.translate_calls += 1
        self.translate_prompts.append(user_prompt)
        # Mirror source indexes with a "FA:" prefix for determinism.
        import json

        payload = json.loads(user_prompt)
        translations = [
            {
                "segment_index": item["segment_index"],
                "text": f"FA:{item['text']}",
            }
            for item in payload["translate_segments"]
        ]
        return LlmGatewayGeneration(
            request_id="t1",
            output={"translations": translations},
            provider="stub",
            model="stub-model",
            provider_request_id="prov-t",
            usage=LlmGatewayTokenUsage(input_tokens=20, output_tokens=12, total_tokens=32),
        )


def _seed_transcript(
    sessionmaker_: sessionmaker[Session],
    *,
    language: str = "en",
    texts: list[str] | None = None,
) -> UUID:
    job_id = uuid4()
    texts = texts or ["Hello Alice", "How are you?"]
    with sessionmaker_() as session:
        session.add(
            Job(
                id=job_id,
                kind=JobKind.TELEGRAM_ATTACHMENT,
                status=JobStatus.COMPLETED,
                idempotency_key=f"src-{job_id}",
            )
        )
        transcript = Transcript(
            job_id=job_id,
            text=" ".join(texts),
            language=language,
        )
        session.add(transcript)
        session.flush()
        for index, text in enumerate(texts):
            session.add(
                TranscriptSegment(
                    transcript_id=transcript.id,
                    segment_index=index,
                    start_ms=index * 1000,
                    end_ms=index * 1000 + 800,
                    text=text,
                )
            )
        session.commit()
    return job_id


def test_skips_when_same_language(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_transcript(content_sync_sessionmaker, language="en")
    client = FakeLlmClient()
    service = SyncSubtitleTranslationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        llm_gateway_client=client,  # type: ignore[arg-type]
    )
    segments = service.ensure_translated(source_job_id=job_id, target_language="en")
    assert [segment.text for segment in segments] == ["Hello Alice", "How are you?"]
    assert client.glossary_calls == 0
    assert client.translate_calls == 0


def test_translates_and_reuses_completed(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_transcript(content_sync_sessionmaker, language="en")
    client = FakeLlmClient()
    service = SyncSubtitleTranslationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        llm_gateway_client=client,  # type: ignore[arg-type]
    )

    first = service.ensure_translated(source_job_id=job_id, target_language="fa")
    assert [segment.text for segment in first] == ["FA:Hello Alice", "FA:How are you?"]
    assert first[0].start_ms == 0
    assert first[0].end_ms == 800
    assert client.glossary_calls == 1
    assert client.translate_calls >= 1

    second_client = FakeLlmClient()
    service2 = SyncSubtitleTranslationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        llm_gateway_client=second_client,  # type: ignore[arg-type]
    )
    second = service2.ensure_translated(source_job_id=job_id, target_language="fa")
    assert [segment.text for segment in second] == ["FA:Hello Alice", "FA:How are you?"]
    assert second_client.glossary_calls == 0
    assert second_client.translate_calls == 0

    with content_sync_sessionmaker() as session:
        translation = session.scalar(
            select(SubtitleTranslation).where(
                SubtitleTranslation.job_id == job_id,
                SubtitleTranslation.target_language == "fa",
            )
        )
        assert translation is not None
        assert translation.status == SubtitleTranslationStatus.COMPLETED
        assert translation.glossary is not None
        segments = list(
            session.scalars(
                select(TranscriptSegment).join(Transcript).where(Transcript.job_id == job_id)
            )
        )
        assert [row.text for row in segments] == ["Hello Alice", "How are you?"]


def test_multi_batch_translation_persists_all_segments(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
    monkeypatch,
) -> None:
    job_id = _seed_transcript(
        content_sync_sessionmaker,
        language="en",
        texts=[f"line {i}" for i in range(6)],
    )

    # Force tiny batches so multi-batch is guaranteed.
    monkeypatch.setattr(settings, "subtitle_translation_max_segments_per_batch", 2)
    monkeypatch.setattr(settings, "subtitle_translation_max_source_tokens", 50)

    client = FakeLlmClient()
    service = SyncSubtitleTranslationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        llm_gateway_client=client,  # type: ignore[arg-type]
    )

    segments = service.ensure_translated(source_job_id=job_id, target_language="fa")
    assert len(segments) == 6
    assert all(segment.text.startswith("FA:") for segment in segments)
    assert client.translate_calls >= 3

    with content_sync_sessionmaker() as session:
        batches = list(session.scalars(select(TranslationBatch)))
        assert len(batches) >= 3
        assert all(batch.status == TranslationBatchStatus.SUCCEEDED for batch in batches)
        translated = list(session.scalars(select(TranslatedSegment)))
        assert len(translated) == 6


def test_overwrite_rejected(
    content_sync_sessionmaker: sessionmaker[Session],
    content_sync_uow_factory,
) -> None:
    job_id = _seed_transcript(content_sync_sessionmaker)
    service = SyncSubtitleTranslationService(
        uow_factory=content_sync_uow_factory,
        settings=settings,
        llm_gateway_client=FakeLlmClient(),  # type: ignore[arg-type]
    )
    with pytest.raises(PermanentContentProcessingError):
        service.ensure_translated(
            source_job_id=job_id,
            target_language="fa",
            overwrite=True,
        )
