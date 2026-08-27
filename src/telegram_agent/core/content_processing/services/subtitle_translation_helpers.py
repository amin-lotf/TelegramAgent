from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from pydantic import ValidationError

from telegram_agent.core.common.exceptions import RetryableContentProcessingError
from telegram_agent.core.common.spoken_text import sanitize_spoken_text
from telegram_agent.core.content_processing.common.language_codes import (
    InvalidLanguageCodeError,
    canonical_madlad_language,
)
from telegram_agent.core.content_processing.db.repositories.sync_subtitle_translation import (
    BatchPlanItem,
)
from telegram_agent.core.llm_gateway.common.schemas import (
    GlossaryExtractionResponse,
    SubtitleBatchTranslationResponse,
)


@dataclass(frozen=True, slots=True)
class SourceSegmentView:
    segment_index: int
    start_ms: int
    end_ms: int
    text: str


def normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    return normalized or None


def languages_match(source: str | None, target: str | None) -> bool:
    source_norm = normalize_language(source)
    target_norm = normalize_language(target)
    if source_norm is None or target_norm is None:
        return False
    if source_norm == target_norm:
        return True
    try:
        return canonical_madlad_language(source) == canonical_madlad_language(target)
    except InvalidLanguageCodeError:
        return False


def estimate_tokens(text: str) -> int:
    cleaned = text.strip()
    if not cleaned:
        return 0
    return max(1, (len(cleaned) + 3) // 4)


def plan_translation_batches(
    segments: Sequence[SourceSegmentView],
    *,
    max_source_tokens: int,
    max_segments: int,
) -> list[BatchPlanItem]:
    if not segments:
        return []

    plans: list[BatchPlanItem] = []
    batch_index = 0
    start = 0
    token_total = 0
    count = 0

    for offset, segment in enumerate(segments):
        tokens = estimate_tokens(segment.text)
        would_exceed = count > 0 and (
            count >= max_segments or token_total + tokens > max_source_tokens
        )
        if would_exceed:
            plans.append(
                BatchPlanItem(
                    batch_index=batch_index,
                    start_segment_index=segments[start].segment_index,
                    end_segment_index=segments[offset - 1].segment_index,
                )
            )
            batch_index += 1
            start = offset
            token_total = 0
            count = 0
        token_total += tokens
        count += 1

    plans.append(
        BatchPlanItem(
            batch_index=batch_index,
            start_segment_index=segments[start].segment_index,
            end_segment_index=segments[-1].segment_index,
        )
    )
    return plans


def build_glossary_windows(
    segments: Sequence[SourceSegmentView],
    *,
    window_token_budget: int,
    max_windows: int,
    max_windows_long: int,
    overlap_ratio: float,
) -> list[list[SourceSegmentView]]:
    if not segments:
        return []

    total_tokens = sum(estimate_tokens(segment.text) for segment in segments)
    if total_tokens <= window_token_budget:
        return [list(segments)]

    ideal_windows = max(1, (total_tokens + window_token_budget - 1) // window_token_budget)
    window_cap = max_windows if ideal_windows <= max_windows else max_windows_long
    window_count = min(window_cap, ideal_windows)

    if window_count <= 1:
        return [list(segments)]

    n = len(segments)
    # Approximate equal-size windows with overlap by segment count.
    base_size = max(1, (n + window_count - 1) // window_count)
    overlap = max(0, int(round(base_size * overlap_ratio)))
    step = max(1, base_size - overlap)

    windows: list[list[SourceSegmentView]] = []
    start = 0
    while start < n and len(windows) < window_count:
        end = min(n, start + base_size)
        # Last window absorbs the tail.
        if len(windows) == window_count - 1:
            end = n
        windows.append(list(segments[start:end]))
        if end >= n:
            break
        start += step
    return windows


def consolidate_glossaries(
    partials: Sequence[dict[str, Any]],
    *,
    max_entries: int,
) -> dict[str, Any]:
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    tone_parts: list[str] = []

    for partial in partials:
        try:
            parsed = GlossaryExtractionResponse.model_validate(partial)
        except ValidationError:
            continue
        if parsed.tone_guidance:
            guidance = parsed.tone_guidance.strip()
            if guidance and guidance not in tone_parts:
                tone_parts.append(guidance)
        for entry in parsed.entries:
            key = (entry.source_term.strip().casefold(), entry.category.value)
            if not key[0]:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = {
                    "source_term": entry.source_term.strip(),
                    "preferred_translation": entry.preferred_translation.strip(),
                    "category": entry.category.value,
                    "expansion": entry.expansion,
                    "notes": entry.notes,
                }
                continue
            if not existing.get("preferred_translation") and entry.preferred_translation:
                existing["preferred_translation"] = entry.preferred_translation.strip()
            if not existing.get("expansion") and entry.expansion:
                existing["expansion"] = entry.expansion
            if not existing.get("notes") and entry.notes:
                existing["notes"] = entry.notes

    entries = list(merged.values())[:max_entries]
    tone = " ".join(tone_parts).strip()
    if len(tone) > 500:
        tone = tone[:500].rstrip()
    return {
        "entries": entries,
        "tone_guidance": tone or None,
    }


def empty_glossary() -> dict[str, Any]:
    return {"entries": [], "tone_guidance": None}


def validate_batch_translations(
    *,
    expected_indexes: set[int],
    output: dict[str, Any],
) -> list[tuple[int, str]]:
    try:
        parsed = SubtitleBatchTranslationResponse.model_validate(output)
    except ValidationError as exc:
        raise RetryableContentProcessingError(
            "Subtitle translation output failed schema validation"
        ) from exc

    by_index: dict[int, str] = {}
    for item in parsed.translations:
        text = sanitize_spoken_text(item.text.strip()).strip()
        if not text:
            raise RetryableContentProcessingError(
                f"Subtitle translation for segment_index={item.segment_index} is empty"
            )
        if item.segment_index in by_index:
            raise RetryableContentProcessingError(
                f"Duplicate translation for segment_index={item.segment_index}"
            )
        by_index[item.segment_index] = text

    actual = set(by_index)
    if actual != expected_indexes:
        missing = sorted(expected_indexes - actual)
        extra = sorted(actual - expected_indexes)
        raise RetryableContentProcessingError(
            "Subtitle translation indexes mismatch"
            f" missing={missing} extra={extra}"
        )

    return [(index, by_index[index]) for index in sorted(expected_indexes)]


def segment_payload(segment: SourceSegmentView) -> dict[str, object]:
    return {
        "segment_index": segment.segment_index,
        "text": segment.text,
    }


def context_pair_payload(
    *,
    source: SourceSegmentView,
    translated_text: str,
) -> dict[str, object]:
    return {
        "segment_index": source.segment_index,
        "source_text": source.text,
        "translated_text": translated_text,
    }
