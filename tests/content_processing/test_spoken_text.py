from telegram_agent.core.common.spoken_text import (
    sanitize_spoken_text,
    wrap_text_normalize,
)


def test_sanitize_spoken_text_unescapes_entities_and_rejoins_contractions() -> None:
    assert sanitize_spoken_text("It &apos;s recycled.") == "It's recycled."
    assert sanitize_spoken_text("we&apos;ve") == "we've"
    assert sanitize_spoken_text("we 've") == "we've"
    assert sanitize_spoken_text("do n't") == "don't"
    assert sanitize_spoken_text("&quot;hello&quot;") == '"hello"'
    assert sanitize_spoken_text("AT&amp;T") == "AT&T"


def test_sanitize_spoken_text_leaves_correct_text_alone() -> None:
    assert sanitize_spoken_text("It's recycled. We've got dishes.") == (
        "It's recycled. We've got dishes."
    )
    assert sanitize_spoken_text("") == ""


def test_wrap_text_normalize_unescapes_entities_and_rejoins_contractions() -> None:
    def fake_normalize(text: str) -> str:
        return text

    wrapped = wrap_text_normalize(fake_normalize)
    assert wrapped("It &apos;s recycled.") == "It's recycled."
    assert wrapped("do n't") == "don't"


def test_wrap_text_normalize_sanitizes_list_results() -> None:
    def fake_normalize(text: str) -> list[str]:
        return [text, "we 've"]

    wrapped = wrap_text_normalize(fake_normalize)
    assert wrapped("It &apos;s") == ["It's", "we've"]
