"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any,  get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.content_processing.common.const import DEFAULT_SQLALCHEMY_DATABASE_URL, \
    DEFAULT_ALLOWED_ORIGINS, \
    DEFAULT_TELEGRAM_AUTH_BASE_URL, DEFAULT_REDIS_URL


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
    auth_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SERVICE_TOKEN", "auth_service_token"),
        description="API token for accessing the authentication service API.",
    )

    content_processing_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CONTENT_PROCESSING_SERVICE_TOKEN", "content_processing_service_token"),
        description="API token for accessing the authentication service API.",
    )

    telegram_auth_base_url: str = Field(
        default=DEFAULT_TELEGRAM_AUTH_BASE_URL,
        validation_alias=AliasChoices("TELEGRAM_AUTH_BASE_URL", "telegram_auth_base_url"),
        description="Base URL for the Telegram authentication service API.",
    )


    sqlalchemy_database_url: str = Field(
        default=DEFAULT_SQLALCHEMY_DATABASE_URL,
        validation_alias=AliasChoices("SQLALCHEMY_DATABASE_URL", "sqlalchemy_database_url"),
        description="Database URL for the application.",
    )



    allowed_origins: str = Field(
        default=DEFAULT_ALLOWED_ORIGINS,
        validation_alias=AliasChoices(
            "ALLOWED_ORIGINS",
            "allowed_origins",
        ),
        description="List of allowed origins (for CORS)"
    )

    redis_url: str = Field(
        default=DEFAULT_REDIS_URL,
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
        description="Redis URL for the application.",
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
