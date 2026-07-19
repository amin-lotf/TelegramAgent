"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.agent_runtime.common.const import (
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_CONTENT_PROCESSING_BASE_URL,
    DEFAULT_CONTENT_PROCESSING_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_COORDINATION_CLAIM_LEASE_SECONDS,
    DEFAULT_COORDINATION_MESSAGE_BATCH_SIZE,
    DEFAULT_COORDINATION_RECENT_WINDOW_SIZE,
    DEFAULT_LLM_GATEWAY_BASE_URL,
    DEFAULT_LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE,
    DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS,
    DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS,
    DEFAULT_OUTBOX_MAX_ATTEMPTS,
    DEFAULT_OUTBOX_RETRY_BASE_SECONDS,
    DEFAULT_OUTBOX_RETRY_MAX_SECONDS,
    DEFAULT_REDIS_URL,
    DEFAULT_SQLALCHEMY_DATABASE_URL,
    DEFAULT_TELEGRAM_INGRESS_BASE_URL,
    DEFAULT_TELEGRAM_INGRESS_REQUEST_TIMEOUT_SECONDS,
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

    telegram_ingress_base_url: str = Field(
        default=DEFAULT_TELEGRAM_INGRESS_BASE_URL,
        validation_alias=AliasChoices("TELEGRAM_INGRESS_BASE_URL", "telegram_ingress_base_url"),
        description="Base URL for the Telegram ingress service API.",
    )

    content_processing_base_url: str = Field(
        default=DEFAULT_CONTENT_PROCESSING_BASE_URL,
        validation_alias=AliasChoices("CONTENT_PROCESSING_BASE_URL", "content_processing_base_url"),
        description="Base URL for the content processing service API.",
    )
    content_processing_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "CONTENT_PROCESSING_SERVICE_TOKEN",
            "content_processing_service_token",
        ),
        description="API token for accessing the content processing service API.",
    )
    telegram_ingress_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TELEGRAM_INGRESS_SERVICE_TOKEN",
            "telegram_ingress_service_token",
        ),
    )
    telegram_ingress_request_timeout_seconds: float = Field(
        default=DEFAULT_TELEGRAM_INGRESS_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "TELEGRAM_INGRESS_REQUEST_TIMEOUT_SECONDS",
            "telegram_ingress_request_timeout_seconds",
        ),
        gt=0,
    )
    content_processing_request_timeout_seconds: float = Field(
        default=DEFAULT_CONTENT_PROCESSING_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "CONTENT_PROCESSING_REQUEST_TIMEOUT_SECONDS",
            "content_processing_request_timeout_seconds",
        ),
        gt=0,
    )

    agent_runtime_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AGENT_RUNTIME_SERVICE_TOKEN",
            "agent_runtime_service_token",
        ),
    )

    llm_gateway_base_url: str = Field(
        default=DEFAULT_LLM_GATEWAY_BASE_URL,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_BASE_URL",
            "llm_gateway_base_url",
        ),
        description="Base URL for the provider-independent LLM gateway.",
    )
    llm_gateway_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_SERVICE_TOKEN",
            "llm_gateway_service_token",
        ),
    )
    llm_gateway_request_timeout_seconds: float = Field(
        default=DEFAULT_LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS",
            "llm_gateway_request_timeout_seconds",
        ),
        gt=0,
    )

    sqlalchemy_database_url: str = Field(
        default=DEFAULT_SQLALCHEMY_DATABASE_URL,
        validation_alias=AliasChoices("SQLALCHEMY_DATABASE_URL", "sqlalchemy_database_url"),
        description="Database URL for the application.",
    )

    redis_url: str = Field(
        default=DEFAULT_REDIS_URL,
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )
    outbox_dispatch_batch_size: int = Field(
        default=DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE,
        validation_alias=AliasChoices("OUTBOX_DISPATCH_BATCH_SIZE", "outbox_dispatch_batch_size"),
        gt=0,
    )
    outbox_dispatch_poll_interval_seconds: float = Field(
        default=DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS,
        validation_alias=AliasChoices(
            "OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS",
            "outbox_dispatch_poll_interval_seconds",
        ),
        gt=0,
    )
    outbox_dispatch_lease_seconds: int = Field(
        default=DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS,
        validation_alias=AliasChoices(
            "OUTBOX_DISPATCH_LEASE_SECONDS",
            "outbox_dispatch_lease_seconds",
        ),
        gt=0,
    )
    outbox_retry_base_seconds: int = Field(
        default=DEFAULT_OUTBOX_RETRY_BASE_SECONDS,
        validation_alias=AliasChoices("OUTBOX_RETRY_BASE_SECONDS", "outbox_retry_base_seconds"),
        gt=0,
    )
    outbox_retry_max_seconds: int = Field(
        default=DEFAULT_OUTBOX_RETRY_MAX_SECONDS,
        validation_alias=AliasChoices("OUTBOX_RETRY_MAX_SECONDS", "outbox_retry_max_seconds"),
        gt=0,
    )
    outbox_max_attempts: int = Field(
        default=DEFAULT_OUTBOX_MAX_ATTEMPTS,
        validation_alias=AliasChoices("OUTBOX_MAX_ATTEMPTS", "outbox_max_attempts"),
        ge=0,
        description=(
            "Maximum number of recorded outbox failures before a retryable "
            "coordination failure is promoted to permanent (message marked vague, "
            "outbox FAILED). When attempt_count already equals this limit, the next "
            "failure is permanent. 0 means the first failure is permanent."
        ),
    )
    coordination_message_batch_size: int = Field(
        default=DEFAULT_COORDINATION_MESSAGE_BATCH_SIZE,
        validation_alias=AliasChoices(
            "COORDINATION_MESSAGE_BATCH_SIZE",
            "coordination_message_batch_size",
        ),
        gt=0,
    )
    coordination_recent_window_size: int = Field(
        default=DEFAULT_COORDINATION_RECENT_WINDOW_SIZE,
        validation_alias=AliasChoices(
            "COORDINATION_RECENT_WINDOW_SIZE",
            "coordination_recent_window_size",
        ),
        gt=0,
    )
    coordination_claim_lease_seconds: int = Field(
        default=DEFAULT_COORDINATION_CLAIM_LEASE_SECONDS,
        validation_alias=AliasChoices(
            "COORDINATION_CLAIM_LEASE_SECONDS",
            "coordination_claim_lease_seconds",
        ),
        gt=0,
        description=(
            "Lease duration for an exclusive conversation claim while a worker "
            "coordinates a bounded batch of messages."
        ),
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
