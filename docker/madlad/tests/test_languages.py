from __future__ import annotations

import pytest

from app.languages import UnknownLanguageError, normalize_to_madlad, target_language_token


def test_normalizes_aliases_tokens_and_generic_codes() -> None:
    assert normalize_to_madlad("English") == "en"
    assert normalize_to_madlad("Persian") == "fa"
    assert normalize_to_madlad("<2fa>") == "fa"
    assert normalize_to_madlad("zh-Hant") == "zh_Hant"
    assert normalize_to_madlad("abc") == "abc"
    assert target_language_token("fa") == "<2fa>"


def test_rejects_invalid_code() -> None:
    with pytest.raises(UnknownLanguageError):
        normalize_to_madlad("not a language")
