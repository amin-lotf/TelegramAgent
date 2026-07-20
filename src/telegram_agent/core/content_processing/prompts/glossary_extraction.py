from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Sequence


SYSTEM_PROMPT = """You extract a compact translation glossary from subtitle transcript segments.

Return only structured glossary data. Do not translate the full transcript.
Identify:
- Person names
- Organization / product names
- Abbreviations with preferred expansions when clear
- Technical / domain terms

For every entry provide:
- source_term (as spoken/written in the source)
- preferred_translation in the target language
- category
- optional expansion (abbreviations)
- optional short notes

Also provide optional tone_guidance (1-3 sentences) for spoken subtitle style in the target language.
Prefer consistency and natural spoken language over literal word-for-word calques.
Deduplicate near-identical terms. Keep the glossary bounded and high-signal."""


@dataclass(frozen=True, slots=True)
class GlossaryExtractionPrompts:
    system_prompt: str
    user_prompt: str


def build_glossary_extraction_prompts(
    *,
    source_language: str | None,
    target_language: str,
    window_segments: Sequence[dict[str, object]],
    window_index: int,
    window_count: int,
) -> GlossaryExtractionPrompts:
    payload = {
        "source_language": source_language,
        "target_language": target_language,
        "window_index": window_index,
        "window_count": window_count,
        "segments": list(window_segments),
    }
    return GlossaryExtractionPrompts(
        system_prompt=SYSTEM_PROMPT,
        user_prompt=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
    )
