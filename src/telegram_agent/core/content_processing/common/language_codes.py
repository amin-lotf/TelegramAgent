"""Language normalization used by local translation provider routing."""

from __future__ import annotations

import re


MADLAD_LANGUAGE_ALIASES: dict[str, str] = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "fa": "fa",
    "fas": "fa",
    "per": "fa",
    "persian": "fa",
    "farsi": "fa",
    "zh": "zh",
    "zh-cn": "zh",
    "zh-hans": "zh",
    "cmn": "zh",
    "chinese": "zh",
    "zh-tw": "zh_Hant",
    "zh-hant": "zh_Hant",
    "ar": "ar",
    "ara": "ar",
    "arabic": "ar",
    "es": "es",
    "spa": "es",
    "spanish": "es",
    "fr": "fr",
    "fra": "fr",
    "fre": "fr",
    "french": "fr",
    "de": "de",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "ja": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "ko": "ko",
    "kor": "ko",
    "korean": "ko",
    "ru": "ru",
    "rus": "ru",
    "russian": "ru",
    "tr": "tr",
    "tur": "tr",
    "turkish": "tr",
    "hi": "hi",
    "hin": "hi",
    "hindi": "hi",
    "pt": "pt",
    "por": "pt",
    "portuguese": "pt",
    "it": "it",
    "ita": "it",
    "italian": "it",
    "nl": "nl",
    "nld": "nl",
    "dutch": "nl",
    "pl": "pl",
    "pol": "pl",
    "polish": "pl",
    "uk": "uk",
    "ukr": "uk",
    "ukrainian": "uk",
    "vi": "vi",
    "vie": "vi",
    "vietnamese": "vi",
    "id": "id",
    "ind": "id",
    "indonesian": "id",
    "th": "th",
    "tha": "th",
    "thai": "th",
    "sv": "sv",
    "swe": "sv",
    "swedish": "sv",
    "he": "he",
    "heb": "he",
    "hebrew": "he",
    "ur": "ur",
    "urd": "ur",
    "urdu": "ur",
}

_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:_[A-Za-z]{4})?$")


class InvalidLanguageCodeError(ValueError):
    """Raised when a language cannot be represented as a MADLAD code."""


def canonical_madlad_language(value: str | None) -> str:
    """Normalize a language name, code, or ``<2xx>`` token."""
    if value is None:
        raise InvalidLanguageCodeError("Language code is required")
    raw = value.strip()
    if raw.startswith("<2") and raw.endswith(">") and len(raw) > 3:
        raw = raw[2:-1]
    if not raw:
        raise InvalidLanguageCodeError("Language code must not be empty")

    alias = MADLAD_LANGUAGE_ALIASES.get(raw.casefold().replace("_", "-"))
    if alias is not None:
        return alias

    parts = raw.replace("-", "_").split("_", 1)
    normalized = parts[0].casefold()
    if len(parts) == 2:
        normalized = f"{normalized}_{parts[1].title()}"
    if not _LANGUAGE_CODE_PATTERN.fullmatch(normalized):
        raise InvalidLanguageCodeError(f"Invalid MADLAD language code: {value!r}")
    return normalized


def parse_madlad_language_pairs(value: str | None) -> frozenset[tuple[str, str]]:
    """Parse comma-separated ``source:target`` MADLAD routing pairs."""
    if value is None or not value.strip():
        return frozenset()

    pairs: set[tuple[str, str]] = set()
    for item in value.split(","):
        raw = item.strip()
        if not raw:
            raise ValueError("MADLAD_LANGUAGE_PAIRS contains an empty entry")
        if raw.count(":") != 1:
            raise ValueError(
                "MADLAD_LANGUAGE_PAIRS entries must use source:target syntax"
            )
        source, target = raw.split(":", 1)
        pairs.add(
            (
                canonical_madlad_language(source),
                canonical_madlad_language(target),
            )
        )
    return frozenset(pairs)


def uses_madlad_pair(
    *,
    configured_pairs: str | None,
    source_language: str | None,
    target_language: str | None,
) -> bool:
    """Return whether the normalized source/target pair is locally configured."""
    if source_language is None or target_language is None:
        return False
    try:
        pair = (
            canonical_madlad_language(source_language),
            canonical_madlad_language(target_language),
        )
    except InvalidLanguageCodeError:
        return False
    return pair in parse_madlad_language_pairs(configured_pairs)
