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


class DownloadAgentVideoResponse(BaseModel):
    """Structured output for video download requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)


class DownloadAgentAudioResponse(BaseModel):
    """Structured output for audio download requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_language: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)


class DownloadAgentDocumentResponse(BaseModel):
    """Structured output for document download requests."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_format: str | None = None
    assistant_text: str = Field(min_length=1, max_length=2_000)


class DownloadAgentResponse(BaseModel):
    """Union envelope used by the download-agent gateway endpoint.

    Exactly one media-type payload is expected based on the request media type;
    the gateway validates against the media-specific schema before returning.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    assistant_text: str = Field(min_length=1, max_length=2_000)
    requested_subtitle_language: str | None = None
    requested_dub_language: str | None = None
    requested_language: str | None = None
    requested_format: str | None = None
