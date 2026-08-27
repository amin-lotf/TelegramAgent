from dataclasses import dataclass


@dataclass(frozen=True)
class ModelTranscriptSegment:
    start_seconds: float
    end_seconds: float
    text: str
    language: str | None = None
    language_probability: float | None = None
    speaker: str | None = None
    speaker_confidence: float | None = None
    word_count: int | None = None


@dataclass(frozen=True)
class ModelTranscriptResult:
    text: str
    segments: list[ModelTranscriptSegment]
    language: str | None = None
    language_probability: float | None = None
    duration_seconds: float | None = None