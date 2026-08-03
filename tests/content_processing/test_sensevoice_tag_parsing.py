from telegram_agent.core.sensevoice.runtime import parse_sensevoice_text


def test_parse_sensevoice_text_extracts_emotion_events_and_language() -> None:
    result = parse_sensevoice_text(
        "<|en|><|HAPPY|><|Speech|><|withitn|>hello there"
    )
    assert result.emotion == "HAPPY"
    assert result.events == ("Speech",)
    assert result.language == "en"
    assert result.text == "hello there"


def test_parse_sensevoice_text_handles_multiple_events() -> None:
    result = parse_sensevoice_text(
        "<|zh|><|SAD|><|Speech|><|Laughter|><|woitn|>ni hao"
    )
    assert result.emotion == "SAD"
    assert result.events == ("Speech", "Laughter")
    assert result.language == "zh"
    assert result.text == "ni hao"


def test_parse_sensevoice_text_without_tags() -> None:
    result = parse_sensevoice_text("plain text only")
    assert result.emotion is None
    assert result.events == ()
    assert result.language is None
    assert result.text == "plain text only"


def test_parse_sensevoice_text_emo_unknown() -> None:
    """SenseVoice often emits EMO_UNKNOWN when confidence is low."""
    result = parse_sensevoice_text(
        "<|en|><|EMO_UNKNOWN|><|Speech|><|withitn|>Probably going to be pretty hard."
    )
    assert result.emotion == "UNKNOWN"
    assert result.events == ("Speech",)
    assert result.language == "en"
    assert result.text == "Probably going to be pretty hard."


def test_parse_sensevoice_text_emo_prefixed_named_emotion() -> None:
    result = parse_sensevoice_text("<|en|><|EMO_NEUTRAL|><|Speech|><|woitn|>okay")
    assert result.emotion == "NEUTRAL"
    assert result.events == ("Speech",)
