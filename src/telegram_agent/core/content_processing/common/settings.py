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

    telegram_bot_token: str = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        description="API token for accessing the Telegram bot API.",
    )

    whisperx_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WHISPERX_SERVICE_TOKEN", "whisperx_service_token"),
        description="API token for accessing the whisperx service API.",
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

    outbox_dispatch_batch_size: int = Field(
        default=50,
        validation_alias=AliasChoices("OUTBOX_DISPATCH_BATCH_SIZE", "outbox_dispatch_batch_size"),
        description="Maximum number of outbox events a dispatcher claims per poll.",
    )

    outbox_dispatch_poll_interval_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS",
            "outbox_dispatch_poll_interval_seconds",
        ),
        description="Celery Beat polling interval for dispatching outbox events.",
    )

    outbox_dispatch_lease_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("OUTBOX_DISPATCH_LEASE_SECONDS", "outbox_dispatch_lease_seconds"),
        description="Seconds before an in-flight outbox dispatch lease can be reclaimed.",
    )

    outbox_retry_base_seconds: int = Field(
        default=5,
        validation_alias=AliasChoices("OUTBOX_RETRY_BASE_SECONDS", "outbox_retry_base_seconds"),
        description="Base delay for outbox exponential retry backoff.",
    )

    outbox_retry_max_seconds: int = Field(
        default=300,
        validation_alias=AliasChoices("OUTBOX_RETRY_MAX_SECONDS", "outbox_retry_max_seconds"),
        description="Maximum delay for outbox exponential retry backoff.",
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
