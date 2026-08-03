from pydantic import BaseModel, Field


class SenseVoiceEmotionResponse(BaseModel):
    emotion: str | None = Field(
        default=None,
        description="Detected emotion label when available.",
    )
    events: list[str] = Field(
        default_factory=list,
        description="Detected audio event labels when available.",
    )
    language: str | None = Field(
        default=None,
        description="Detected language when available.",
    )
    text: str | None = Field(
        default=None,
        description="Plain ASR text from SenseVoice when available.",
    )
    model: str = Field(..., description="SenseVoice model used for extraction.")
