from pydantic import BaseModel, Field


class WhisperXTranscriptSegmentResponse(BaseModel):
    start: float = Field(..., description="Segment start time in seconds.")
    end: float = Field(..., description="Segment end time in seconds.")
    text: str = Field(..., description="Transcript text for the segment.")
    language: str | None = Field(
        default=None,
        description="Detected language for the segment when available.",
    )
    language_probability: float | None = Field(
        default=None,
        description="Detected language probability when available.",
    )
    speaker: str | None = Field(
        default=None,
        description="Assigned speaker label when diarization is enabled.",
    )
    speaker_confidence: float | None = Field(
        default=None,
        description="Speaker confidence when provided by the pipeline.",
    )


class WhisperXTranscriptResponse(BaseModel):
    text: str = Field(..., description="Full transcript text.")
    segments: list[WhisperXTranscriptSegmentResponse] = Field(
        default_factory=list,
        description="Timestamped transcript segments.",
    )
    language: str | None = Field(
        default=None,
        description="Detected transcript language.",
    )
    language_probability: float | None = Field(
        default=None,
        description="Detected transcript language confidence when available.",
    )
    duration: float | None = Field(
        default=None,
        description="Transcript duration in seconds.",
    )
    model: str = Field(..., description="WhisperX model used for the transcription.")
