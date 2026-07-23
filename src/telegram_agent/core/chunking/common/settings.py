"""Runtime configuration loaded from environment variables and .env."""
from __future__ import annotations

import sys
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.chunking.common.const import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_CHUNK_CHARS,
    DEFAULT_MAX_CHUNK_TOKENS,
    DEFAULT_OVERLAP_DURATION_MS,
    DEFAULT_OVERLAP_SEGMENTS,
    DEFAULT_TARGET_CHUNK_DURATION_MS,
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

    chunking_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHUNKING_SERVICE_TOKEN", "chunking_service_token"),
        description="API token for accessing the chunking service API.",
    )

    target_chunk_duration_ms: int = Field(
        default=DEFAULT_TARGET_CHUNK_DURATION_MS,
        validation_alias=AliasChoices(
            "TARGET_CHUNK_DURATION_MS",
            "target_chunk_duration_ms",
        ),
        gt=0,
    )
    max_chunk_chars: int = Field(
        default=DEFAULT_MAX_CHUNK_CHARS,
        validation_alias=AliasChoices("MAX_CHUNK_CHARS", "max_chunk_chars"),
        gt=0,
    )
    max_chunk_tokens: int = Field(
        default=DEFAULT_MAX_CHUNK_TOKENS,
        validation_alias=AliasChoices("MAX_CHUNK_TOKENS", "max_chunk_tokens"),
        gt=0,
    )
    overlap_duration_ms: int = Field(
        default=DEFAULT_OVERLAP_DURATION_MS,
        validation_alias=AliasChoices("OVERLAP_DURATION_MS", "overlap_duration_ms"),
        ge=0,
    )
    overlap_segments: int = Field(
        default=DEFAULT_OVERLAP_SEGMENTS,
        validation_alias=AliasChoices("OVERLAP_SEGMENTS", "overlap_segments"),
        ge=0,
    )

    allowed_origins: str = Field(
        default=DEFAULT_ALLOWED_ORIGINS,
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "allowed_origins"),
        description="List of allowed origins (for CORS)",
    )

    LOG_LEVEL: str = Field(
        default=DEFAULT_LOG_LEVEL,
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
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
