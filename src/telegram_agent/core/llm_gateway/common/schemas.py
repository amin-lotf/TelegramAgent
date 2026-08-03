from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MessageGroupingKind(StrEnum):
    EXISTING = "existing"
    NEW = "new"
    VAGUE = "vague"


class MessageGroupingResponse(BaseModel):
    """Fixed structured-output schema for message-group coordination."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: MessageGroupingKind
    group_number: int | None = Field(default=None)

    @model_validator(mode="after")
    def validate_group_number(self) -> "MessageGroupingResponse":
        if self.kind == MessageGroupingKind.EXISTING:
            if self.group_number is None or self.group_number < 1:
                raise ValueError("EXISTING decisions require a positive group_number")
        elif self.group_number is not None:
            raise ValueError("Only EXISTING decisions may include group_number")
        return self


class IntentKind(StrEnum):
    CONVERSATION = "conversation"
    DOWNLOAD_REQUEST = "download_request"


class IntentClassificationResponse(BaseModel):
    """Fixed structured-output schema for intent classification."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: IntentKind


def _clear_extraction_if_not_download(data: object) -> object:
    """Coerce extraction fields to null when is_download_request is false."""
    if not isinstance(data, dict):
        return data
    if data.get("is_download_request") is False:
        for key in (
            "requested_subtitle_language",
            "requested_dub_language",
            "requested_language",
            "requested_format",
        ):
            if key in data:
                data[key] = None
    return data


class DownloadAgentVideoResponse(BaseModel):
    """Structured output for video download requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_download_request: bool
    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="before")
    @classmethod
    def clear_extraction_when_not_download(cls, data: object) -> object:
        return _clear_extraction_if_not_download(data)


class DownloadAgentAudioResponse(BaseModel):
    """Structured output for audio download requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_download_request: bool
    requested_language: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="before")
    @classmethod
    def clear_extraction_when_not_download(cls, data: object) -> object:
        return _clear_extraction_if_not_download(data)


class DownloadAgentDocumentResponse(BaseModel):
    """Structured output for document download requests.

    Subtitle/dub fields are included because Telegram often classifies video
    containers (MKV, large files) as documents rather than video attachments.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_download_request: bool
    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    requested_format: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)

    @model_validator(mode="before")
    @classmethod
    def clear_extraction_when_not_download(cls, data: object) -> object:
        return _clear_extraction_if_not_download(data)


class DownloadAgentResponse(BaseModel):
    """Union envelope used by the download-agent gateway endpoint.

    Exactly one media-type payload is expected based on the request media type;
    the gateway validates against the media-specific schema before returning.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    is_download_request: bool
    assistant_text: str = Field(min_length=1, max_length=2_000)
    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    requested_language: str | None = None
    requested_format: str | None = None

    @model_validator(mode="before")
    @classmethod
    def clear_extraction_when_not_download(cls, data: object) -> object:
        return _clear_extraction_if_not_download(data)


class GlossaryTermCategory(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"
    PRODUCT = "product"
    ABBREVIATION = "abbreviation"
    TECHNICAL = "technical"
    OTHER = "other"


class GlossaryEntry(BaseModel):
    """One glossary term with preferred target-language rendering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_term: str = Field(min_length=1, max_length=200)
    preferred_translation: str = Field(min_length=1, max_length=200)
    category: GlossaryTermCategory = GlossaryTermCategory.OTHER
    expansion: str | None = Field(default=None, max_length=300)
    notes: str | None = Field(default=None, max_length=300)


class GlossaryExtractionResponse(BaseModel):
    """Structured glossary extraction for subtitle translation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    entries: list[GlossaryEntry] = Field(default_factory=list, max_length=200)
    tone_guidance: str | None = Field(default=None, max_length=500)


class SubtitleTranslationItem(BaseModel):
    """One translated subtitle segment (text only; timings are never model-owned)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=4_000)


class SubtitleBatchTranslationResponse(BaseModel):
    """Structured batch translation output for subtitle segments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    translations: list[SubtitleTranslationItem] = Field(min_length=1, max_length=50)
