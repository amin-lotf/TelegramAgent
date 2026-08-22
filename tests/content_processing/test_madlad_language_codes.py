from __future__ import annotations

import pytest

from telegram_agent.core.content_processing.common.language_codes import (
    InvalidLanguageCodeError,
    canonical_madlad_language,
    parse_madlad_language_pairs,
    uses_madlad_pair,
)
from telegram_agent.core.content_processing.common.settings import Settings


def test_canonicalizes_codes_names_and_target_tokens() -> None:
    assert canonical_madlad_language(" English ") == "en"
    assert canonical_madlad_language("Persian") == "fa"
    assert canonical_madlad_language("<2fa>") == "fa"
    assert canonical_madlad_language("zh-Hant") == "zh_Hant"


def test_parses_multiple_pairs_and_matches_aliases() -> None:
    pairs = parse_madlad_language_pairs(" en:fa, EN:es ")
    assert pairs == frozenset({("en", "fa"), ("en", "es")})
    assert uses_madlad_pair(
        configured_pairs="en:fa",
        source_language="English",
        target_language="Farsi",
    )
    assert not uses_madlad_pair(
        configured_pairs="en:fa",
        source_language="fa",
        target_language="en",
    )


@pytest.mark.parametrize("value", ["en-fa", "en:fa,", ":fa", "en:"])
def test_invalid_pair_configuration_is_rejected(value: str) -> None:
    with pytest.raises((ValueError, InvalidLanguageCodeError)):
        parse_madlad_language_pairs(value)


def test_settings_fail_fast_for_invalid_pair_configuration() -> None:
    with pytest.raises(ValueError):
        Settings(MADLAD_LANGUAGE_PAIRS="en-fa")
