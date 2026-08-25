"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any,  get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.whisperx.common.const import DEFAULT_WHISPERX_MODEL


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
