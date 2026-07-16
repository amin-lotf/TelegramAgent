"""LLM gateway configuration loaded from environment variables and .env."""
from __future__ import annotations

import sys

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.llm_gateway.common.const import (
    DEFAULT_OPENAI_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_OPENAI_MAX_RETRIES,
    DEFAULT_OPENAI_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_REPLY_MODEL,
    DEFAULT_REPLY_TEMPERATURE,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_parse_none_str="None",
        extra="ignore",
    )

    llm_gateway_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_SERVICE_TOKEN",
            "llm_gateway_service_token",
        ),
    )
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "openai_api_key"),
    )
    openai_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_BASE_URL", "openai_base_url"),
    )

    reply_model: str = Field(
        default=DEFAULT_REPLY_MODEL,
        validation_alias=AliasChoices(
            "REPLY_MODEL",
            "reply_model",
        ),
    )

    reply_temperature: float = Field(
        default=DEFAULT_REPLY_TEMPERATURE,
        validation_alias=AliasChoices(
            "REPLY_TEMPERATURE",
            "reply_temperature",
        ),
        ge=0,
        le=2,
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
    LOG_LEVEL: str = Field(default="INFO")

    @field_validator("openai_api_key", "openai_base_url", "llm_gateway_service_token")
    @classmethod
    def _blank_optional_strings_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def load_settings_or_die() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        print("[CONFIG ERROR] Invalid LLM gateway configuration:", file=sys.stderr)
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", []))
            print(f"  - {location}: {error.get('msg', 'invalid value')}", file=sys.stderr)
        sys.exit(2)


settings = load_settings_or_die()
