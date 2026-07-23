"""Runtime configuration loaded from environment variables and .env."""
from __future__ import annotations

import sys
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.embedding.common.const import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_EMBEDDING_DIMENSIONS,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MAX_EMBEDDING_BATCH_SIZE,
    DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
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

    embedding_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "EMBEDDING_SERVICE_TOKEN",
            "embedding_service_token",
        ),
        description="API token for accessing the embedding service API.",
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "openai_base_url"),
    )
    embedding_model: str = Field(
        default=DEFAULT_EMBEDDING_MODEL,
        validation_alias=AliasChoices("EMBEDDING_MODEL", "embedding_model"),
        min_length=1,
    )
    embedding_dimensions: int | None = Field(
        default=DEFAULT_EMBEDDING_DIMENSIONS,
        validation_alias=AliasChoices(
            "EMBEDDING_DIMENSIONS",
            "embedding_dimensions",
        ),
        gt=0,
    )
    openai_request_timeout_seconds: float = Field(
        default=DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "OPENAI_REQUEST_TIMEOUT_SECONDS",
            "openai_request_timeout_seconds",
        ),
        gt=0,
    )
    openai_connect_timeout_seconds: float = Field(
        default=DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "OPENAI_CONNECT_TIMEOUT_SECONDS",
            "openai_connect_timeout_seconds",
        ),
        gt=0,
    )
    openai_max_retries: int = Field(
        default=DEFAULT_OPENAI_MAX_RETRIES,
        validation_alias=AliasChoices(
            "OPENAI_MAX_RETRIES",
            "openai_max_retries",
        ),
        ge=0,
        le=10,
    )
    max_embedding_batch_size: int = Field(
        default=DEFAULT_MAX_EMBEDDING_BATCH_SIZE,
        validation_alias=AliasChoices(
            "MAX_EMBEDDING_BATCH_SIZE",
            "max_embedding_batch_size",
        ),
        gt=0,
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
