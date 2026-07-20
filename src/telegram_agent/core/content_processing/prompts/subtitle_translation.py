from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence


SYSTEM_PROMPT = """You translate subtitle transcript segments into natural spoken target-language subtitles.

Rules:
- Translate ONLY the current batch segments listed under translate_segments.
- Do NOT translate previous_context (already translated; for consistency only).
- Do NOT translate upcoming_segments (context for sentence boundaries only).
- Follow the glossary preferred translations for names, products, abbreviations, and domain terms.
- Preserve meaning; prefer natural spoken language suitable for on-screen subtitles.
- Return exactly one translation for every requested segment_index and no extras.
- Translations must be non-empty.
- Never invent, drop, or renumber segment indexes.
- Never modify or invent timestamps."""


@dataclass(frozen=True, slots=True)
class SubtitleTranslationPrompts:
    system_prompt: str
    user_prompt: str


def build_subtitle_translation_prompts(
    *,
    source_language: str | None,
    target_language: str,
    glossary: dict[str, Any],
    previous_context: Sequence[dict[str, object]],
    translate_segments: Sequence[dict[str, object]],
    upcoming_segments: Sequence[dict[str, object]],
) -> SubtitleTranslationPrompts:
    payload = {
        "source_language": source_language,
        "target_language": target_language,
        "glossary": glossary,
        "previous_context": list(previous_context),
        "translate_segments": list(translate_segments),
        "upcoming_segments": list(upcoming_segments),
    }
    return SubtitleTranslationPrompts(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
