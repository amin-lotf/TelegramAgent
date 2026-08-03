from dataclasses import dataclass


@dataclass(frozen=True)
class ModelEmotionResult:
    emotion: str | None
    events: tuple[str, ...]
    language: str | None = None
    text: str | None = None
