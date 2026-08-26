"""MADLAD target-language aliases and token construction."""

from __future__ import annotations

import logging
import re

LANGUAGE_ALIASES: dict[str, str] = {
    "en": "en", "eng": "en", "english": "en",
    "fa": "fa", "fas": "fa", "per": "fa", "persian": "fa", "farsi": "fa",
    "zh": "zh", "zh-cn": "zh", "zh-hans": "zh", "cmn": "zh",
    "chinese": "zh", "zh-tw": "zh_Hant", "zh-hant": "zh_Hant",
    "ar": "ar", "ara": "ar", "arabic": "ar",
    "es": "es", "spa": "es", "spanish": "es",
    "fr": "fr", "fra": "fr", "fre": "fr", "french": "fr",
    "de": "de", "deu": "de", "ger": "de", "german": "de",
    "ja": "ja", "jpn": "ja", "japanese": "ja",
    "ko": "ko", "kor": "ko", "korean": "ko",
    "ru": "ru", "rus": "ru", "russian": "ru",
    "tr": "tr", "tur": "tr", "turkish": "tr",
    "hi": "hi", "hin": "hi", "hindi": "hi",
    "pt": "pt", "por": "pt", "portuguese": "pt",
    "it": "it", "ita": "it", "italian": "it",
    "nl": "nl", "nld": "nl", "dutch": "nl",
    "pl": "pl", "pol": "pl", "polish": "pl",
    "uk": "uk", "ukr": "uk", "ukrainian": "uk",
    "vi": "vi", "vie": "vi", "vietnamese": "vi",
    "id": "id", "ind": "id", "indonesian": "id",
    "th": "th", "tha": "th", "thai": "th",
    "sv": "sv", "swe": "sv", "swedish": "sv",
    "he": "he", "heb": "he", "hebrew": "he",
    "ur": "ur", "urd": "ur", "urdu": "ur",
}

_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:_[A-Za-z]{4})?$")
logger = logging.getLogger(__name__)


class UnknownLanguageError(ValueError):
    pass


def strip_target_token(code: str) -> str:
    raw = code.strip()
    if raw.startswith("<2") and raw.endswith(">") and len(raw) > 3:
        return raw[2:-1]
    return raw


def target_language_token(lang_code: str) -> str:
    return f"<2{lang_code}>"


def normalize_to_madlad(code: str) -> str:
    raw = strip_target_token((code or "").strip())
    if not raw:
        raise UnknownLanguageError("Language code must not be empty")
    mapped = LANGUAGE_ALIASES.get(raw.casefold().replace("_", "-"))
    if mapped is not None:
        return mapped
    parts = raw.replace("-", "_").split("_", 1)
    normalized = parts[0].casefold()
    if len(parts) == 2:
        normalized = f"{normalized}_{parts[1].title()}"
    if not _LANGUAGE_CODE_PATTERN.fullmatch(normalized):
        raise UnknownLanguageError(f"Invalid MADLAD language code: {code!r}")
    return normalized


def list_aliases() -> dict[str, str]:
    return dict(sorted(LANGUAGE_ALIASES.items()))


def parse_lora_languages(value: str | None) -> tuple[str, ...]:
    """Parse comma-separated MADLAD_LOAD_LORA_FOR language codes."""
    if value is None or not str(value).strip():
        return ()
    seen: list[str] = []
    for item in str(value).split(","):
        raw = item.strip()
        if not raw:
            continue
        try:
            lang = normalize_to_madlad(raw)
        except UnknownLanguageError:
            logger.warning("Ignoring invalid MADLAD_LOAD_LORA_FOR entry %r", raw)
            continue
        if lang not in seen:
            seen.append(lang)
    return tuple(seen)
