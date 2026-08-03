"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.sensevoice.common.const import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_SENSEVOICE_BASE_URL,
    DEFAULT_SENSEVOICE_MODEL,
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

    sensevoice_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "SENSEVOICE_SERVICE_TOKEN",
            "sensevoice_service_token",
        ),
        description="API token for accessing the sensevoice service API.",
    )

    sensevoice_base_url: str = Field(
        default=DEFAULT_SENSEVOICE_BASE_URL,
        validation_alias=AliasChoices("SENSEVOICE_BASE_URL", "sensevoice_base_url"),
        description="Base URL for the SenseVoice emotion extraction service.",
    )

    sensevoice_model: str = Field(
        default=DEFAULT_SENSEVOICE_MODEL,
        validation_alias=AliasChoices("SENSEVOICE_MODEL", "sensevoice_model"),
        description="SenseVoice model name for the service and client.",
        min_length=1,
    )

    sensevoice_device: str = Field(
        default="cuda",
        validation_alias=AliasChoices("SENSEVOICE_DEVICE", "sensevoice_device"),
        description="Device used by the SenseVoice service.",
        min_length=1,
    )

    sensevoice_concurrency: int = Field(
        default=1,
        validation_alias=AliasChoices(
            "SENSEVOICE_CONCURRENCY",
            "sensevoice_concurrency",
        ),
        description="Maximum concurrent SenseVoice emotion extractions per service process.",
        gt=0,
    )

    allowed_origins: str = Field(
        default=DEFAULT_ALLOWED_ORIGINS,
        validation_alias=AliasChoices(
            "ALLOWED_ORIGINS",
            "allowed_origins",
        ),
        description="List of allowed origins (for CORS)",
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
