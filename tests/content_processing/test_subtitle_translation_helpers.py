from __future__ import annotations

import pytest

from telegram_agent.core.common.exceptions import RetryableContentProcessingError
from telegram_agent.core.content_processing.services.subtitle_translation_helpers import (
    SourceSegmentView,
    build_glossary_windows,
    consolidate_glossaries,
    estimate_tokens,
    languages_match,
    normalize_language,
    plan_translation_batches,
    validate_batch_translations,
)


def _seg(index: int, text: str) -> SourceSegmentView:
    return SourceSegmentView(
        segment_index=index,
        start_ms=index * 1000,
        end_ms=index * 1000 + 900,
        text=text,
    )


def test_normalize_and_match_languages() -> None:
    assert normalize_language(" EN ") == "en"
    assert languages_match("en", "EN")
    assert not languages_match("en", "fa")
    assert not languages_match(None, "en")


def test_plan_translation_batches_respects_segment_and_token_limits() -> None:
    segments = [_seg(i, "word " * 20) for i in range(10)]
    plans = plan_translation_batches(
        segments,
        max_source_tokens=50,
        max_segments=3,
    )
    assert len(plans) >= 3
    assert plans[0].start_segment_index == 0
    assert plans[-1].end_segment_index == 9
    # Ranges are contiguous and non-overlapping by segment order.
    for left, right in zip(plans, plans[1:]):
        assert left.end_segment_index < right.start_segment_index


def test_plan_translation_batches_single_batch_for_short_content() -> None:
    segments = [_seg(0, "hello"), _seg(1, "world")]
    plans = plan_translation_batches(
        segments,
        max_source_tokens=3000,
        max_segments=18,
    )
    assert len(plans) == 1
    assert plans[0].start_segment_index == 0
    assert plans[0].end_segment_index == 1


def test_build_glossary_windows_prefers_few_windows() -> None:
    segments = [_seg(i, "x" * 80) for i in range(30)]
    windows = build_glossary_windows(
        segments,
        window_token_budget=40,
        max_windows=3,
        max_windows_long=8,
        overlap_ratio=0.12,
    )
    assert 1 <= len(windows) <= 8
    flat = [seg.segment_index for window in windows for seg in window]
    assert 0 in flat
    assert 29 in flat


def test_consolidate_glossaries_dedupes_and_caps() -> None:
    partials = [
        {
            "entries": [
                {
                    "source_term": "OpenAI",
                    "preferred_translation": "اوپن‌ای‌آی",
                    "category": "organization",
                    "expansion": None,
                    "notes": "company",
                }
            ],
            "tone_guidance": "Natural spoken Persian.",
        },
        {
            "entries": [
                {
                    "source_term": "openai",
                    "preferred_translation": "اوپن ای آی",
                    "category": "organization",
                    "expansion": None,
                    "notes": None,
                },
                {
                    "source_term": "API",
                    "preferred_translation": "ای‌پی‌آی",
                    "category": "abbreviation",
                    "expansion": "Application Programming Interface",
                    "notes": None,
                },
            ],
            "tone_guidance": "Keep it conversational.",
        },
    ]
    glossary = consolidate_glossaries(partials, max_entries=1)
    assert len(glossary["entries"]) == 1
    assert glossary["entries"][0]["source_term"] == "OpenAI"
    assert glossary["entries"][0]["notes"] == "company"
    assert "Natural spoken Persian" in (glossary["tone_guidance"] or "")


def test_validate_batch_translations_accepts_exact_indexes() -> None:
    result = validate_batch_translations(
        expected_indexes={1, 2},
        output={
            "translations": [
                {"segment_index": 2, "text": "two"},
                {"segment_index": 1, "text": "one"},
            ]
        },
    )
    assert result == [(1, "one"), (2, "two")]


def test_validate_batch_translations_rejects_missing_or_empty() -> None:
    with pytest.raises(RetryableContentProcessingError):
        validate_batch_translations(
            expected_indexes={0, 1},
            output={"translations": [{"segment_index": 0, "text": "only"}]},
        )
    with pytest.raises(RetryableContentProcessingError):
        validate_batch_translations(
            expected_indexes={0},
            output={"translations": [{"segment_index": 0, "text": "  "}]},
        )


def test_estimate_tokens_is_positive_for_text() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") >= 1
