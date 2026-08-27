"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any,  get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.whisperx.common.const import (
    DEFAULT_WHISPERX_MERGE_SAME_SPEAKER_ONLY,
    DEFAULT_WHISPERX_MODEL,
    DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
    DEFAULT_WHISPERX_SEGMENT_MIN_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_MIN_WORD_COUNT,
    DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_TARGET_DURATION_SECONDS,
    DEFAULT_WHISPERX_SEGMENT_TARGET_WORD_COUNT,
)


def _is_optional_string(annotation: Any) -> bool:
    args = get_args(annotation)
    return len(args) == 2 and str in args and type(None) in args


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_parse_none_str="None",
        extra="ignore",
    )

    whisperx_model: str = Field(
        default=DEFAULT_WHISPERX_MODEL,
        validation_alias=AliasChoices("WHISPERX_MODEL", "whisperx_model"),
        description="WhisperX model name for the service and client.",
        min_length=1,
    )

    whisperx_device: str = Field(
        default="cuda",
        validation_alias=AliasChoices("WHISPERX_DEVICE", "whisperx_device"),
        description="Device used by the WhisperX service.",
        min_length=1,
    )

    whisperx_compute_type: str = Field(
        default="float16",
        validation_alias=AliasChoices(
            "WHISPERX_COMPUTE_TYPE",
            "whisperx_compute_type",
        ),
        description="Compute type used by the WhisperX service.",
        min_length=1,
    )

    whisperx_batch_size: int = Field(
        default=16,
        validation_alias=AliasChoices(
            "WHISPERX_BATCH_SIZE",
            "whisperx_batch_size",
        ),
        description="Batch size used by the WhisperX service.",
        gt=0,
    )

    whisperx_diarization_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "WHISPERX_DIARIZATION_ENABLED",
            "whisperx_diarization_enabled",
        ),
        description="Enable speaker diarization in the WhisperX service.",
    )

    whisperx_hf_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WHISPERX_HF_TOKEN", "whisperx_hf_token"),
        description="Hugging Face token used by WhisperX diarization models.",
    )

    whisperx_concurrency: int = Field(
        default=1,
        validation_alias=AliasChoices(
            "WHISPERX_CONCURRENCY",
            "whisperx_concurrency",
        ),
        description="Maximum concurrent WhisperX transcriptions per service process.",
        gt=0,
    )

    whisperx_merge_same_speaker_only: bool = Field(
        default=DEFAULT_WHISPERX_MERGE_SAME_SPEAKER_ONLY,
        validation_alias=AliasChoices(
            "WHISPERX_MERGE_SAME_SPEAKER_ONLY",
            "whisperx_merge_same_speaker_only",
        ),
        description=(
            "When merging adjacent Whisper segments, refuse to merge when both "
            "segments have known different speakers."
        ),
    )

    whisperx_segment_target_duration_seconds: float = Field(
        default=DEFAULT_WHISPERX_SEGMENT_TARGET_DURATION_SECONDS,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_TARGET_DURATION_SECONDS",
            "whisperx_segment_target_duration_seconds",
        ),
        gt=0,
        description="Preferred duration for a word-aligned transcript segment.",
    )
    whisperx_segment_min_duration_seconds: float = Field(
        default=DEFAULT_WHISPERX_SEGMENT_MIN_DURATION_SECONDS,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_MIN_DURATION_SECONDS",
            "whisperx_segment_min_duration_seconds",
        ),
        gt=0,
        description="Minimum useful duration used when rebalancing transcript segments.",
    )
    whisperx_segment_max_duration_seconds: float = Field(
        default=DEFAULT_WHISPERX_SEGMENT_MAX_DURATION_SECONDS,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_MAX_DURATION_SECONDS",
            "whisperx_segment_max_duration_seconds",
        ),
        gt=0,
        description="Hard maximum duration for word-aligned transcript segments.",
    )
    whisperx_segment_target_word_count: int = Field(
        default=DEFAULT_WHISPERX_SEGMENT_TARGET_WORD_COUNT,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_TARGET_WORD_COUNT",
            "whisperx_segment_target_word_count",
        ),
        gt=0,
        description="Preferred aligned word-unit count per transcript segment.",
    )
    whisperx_segment_min_word_count: int = Field(
        default=DEFAULT_WHISPERX_SEGMENT_MIN_WORD_COUNT,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_MIN_WORD_COUNT",
            "whisperx_segment_min_word_count",
        ),
        gt=0,
        description="Minimum useful aligned word-unit count used when rebalancing.",
    )
    whisperx_segment_max_word_count: int = Field(
        default=DEFAULT_WHISPERX_SEGMENT_MAX_WORD_COUNT,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_MAX_WORD_COUNT",
            "whisperx_segment_max_word_count",
        ),
        gt=0,
        description="Hard maximum aligned word-unit count per transcript segment.",
    )
    whisperx_segment_pause_seconds: float = Field(
        default=DEFAULT_WHISPERX_SEGMENT_PAUSE_SECONDS,
        validation_alias=AliasChoices(
            "WHISPERX_SEGMENT_PAUSE_SECONDS",
            "whisperx_segment_pause_seconds",
        ),
        gt=0,
        description="Inter-word gap treated as a meaningful split boundary.",
    )

    LOG_LEVEL: str = Field(
        default="DEBUG",
        description="Logging level for the application.",
    )




    @model_validator(mode="before")
    @classmethod
    def _blank_optional_strings_to_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        for field_name, field_info in cls.model_fields.items():
            if not _is_optional_string(field_info.annotation):
                continue

            value = normalized.get(field_name)
            if isinstance(value, str) and not value.strip():
                normalized[field_name] = None
        return normalized

    @model_validator(mode="after")
    def _validate_whisperx_segment_limits(self) -> "Settings":
        if not (
            self.whisperx_segment_min_duration_seconds
            <= self.whisperx_segment_target_duration_seconds
            <= self.whisperx_segment_max_duration_seconds
        ):
            raise ValueError(
                "WhisperX segment duration limits must satisfy minimum <= target <= maximum"
            )
        if not (
            self.whisperx_segment_min_word_count
            <= self.whisperx_segment_target_word_count
            <= self.whisperx_segment_max_word_count
        ):
            raise ValueError(
                "WhisperX segment word-count limits must satisfy minimum <= target <= maximum"
            )
        return self


def load_settings_or_die() -> Settings:
    try:
        return Settings()
    except ValidationError as e:
        print("[CONFIG ERROR] Invalid environment configuration:", file=sys.stderr)
        for err in e.errors():
            loc = ".".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "invalid value")
            print(f"  - {loc}: {msg}", file=sys.stderr)
        sys.exit(2)


settings = load_settings_or_die()
