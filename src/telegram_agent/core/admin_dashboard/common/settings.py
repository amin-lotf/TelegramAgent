"""Runtime configuration loaded from environment variables and .env."""
from __future__ import annotations

import sys
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.admin_dashboard.common.const import (
    DEFAULT_ADMIN_USERNAME,
    DEFAULT_AGENT_RUNTIME_RO_DATABASE_URL,
    DEFAULT_ALLOWED_ORIGINS,
    DEFAULT_CONTENT_PROCESSING_RO_DATABASE_URL,
    DEFAULT_DB_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_DB_POOL_MAX_OVERFLOW,
    DEFAULT_DB_POOL_SIZE,
    DEFAULT_DB_QUERY_TIMEOUT_SECONDS,
    DEFAULT_ENABLE_AUTH_DB_ENRICHMENT,
    DEFAULT_LIST_MAX_PAGE_SIZE,
    DEFAULT_LIST_PAGE_SIZE,
    DEFAULT_LOG_LEVEL,
    DEFAULT_MASK_MEDIA_PATHS,
    DEFAULT_MASK_MESSAGE_TEXT,
    DEFAULT_SESSION_COOKIE_NAME,
    DEFAULT_SESSION_HTTPS_ONLY,
    DEFAULT_TELEGRAM_AUTH_RO_DATABASE_URL,
    DEFAULT_TELEGRAM_INGRESS_RO_DATABASE_URL,
)


def _is_optional_string(annotation: Any) -> bool:
    args = get_args(annotation)
    return len(args) == 2 and str in args and type(None) in args


class Settings(BaseSettings):
    """Admin dashboard settings. Every field must appear in the docker env example."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_parse_none_str="None",
        extra="ignore",
    )

    telegram_ingress_ro_database_url: str = Field(
        default=DEFAULT_TELEGRAM_INGRESS_RO_DATABASE_URL,
        validation_alias=AliasChoices(
            "TELEGRAM_INGRESS_RO_DATABASE_URL",
            "telegram_ingress_ro_database_url",
        ),
        description="Read-only DSN for the telegram-ingress database.",
    )
    content_processing_ro_database_url: str = Field(
        default=DEFAULT_CONTENT_PROCESSING_RO_DATABASE_URL,
        validation_alias=AliasChoices(
            "CONTENT_PROCESSING_RO_DATABASE_URL",
            "content_processing_ro_database_url",
        ),
        description="Read-only DSN for the content-processing database.",
    )
    agent_runtime_ro_database_url: str = Field(
        default=DEFAULT_AGENT_RUNTIME_RO_DATABASE_URL,
        validation_alias=AliasChoices(
            "AGENT_RUNTIME_RO_DATABASE_URL",
            "agent_runtime_ro_database_url",
        ),
        description="Read-only DSN for the agent-runtime database.",
    )
    telegram_auth_ro_database_url: str = Field(
        default=DEFAULT_TELEGRAM_AUTH_RO_DATABASE_URL,
        validation_alias=AliasChoices(
            "TELEGRAM_AUTH_RO_DATABASE_URL",
            "telegram_auth_ro_database_url",
        ),
        description="Read-only DSN for the telegram-auth database.",
    )

    admin_username: str = Field(
        default=DEFAULT_ADMIN_USERNAME,
        validation_alias=AliasChoices("ADMIN_USERNAME", "admin_username"),
    )
    admin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("ADMIN_PASSWORD", "admin_password"),
        description="Plaintext admin password for v1 bootstrap auth.",
    )
    session_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SESSION_SECRET", "session_secret"),
        description="Secret used to sign session cookies.",
    )
    session_cookie_name: str = Field(
        default=DEFAULT_SESSION_COOKIE_NAME,
        validation_alias=AliasChoices("SESSION_COOKIE_NAME", "session_cookie_name"),
    )
    session_https_only: bool = Field(
        default=DEFAULT_SESSION_HTTPS_ONLY,
        validation_alias=AliasChoices("SESSION_HTTPS_ONLY", "session_https_only"),
    )

    db_query_timeout_seconds: float = Field(
        default=DEFAULT_DB_QUERY_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "DB_QUERY_TIMEOUT_SECONDS",
            "db_query_timeout_seconds",
        ),
        gt=0,
    )
    db_connect_timeout_seconds: float = Field(
        default=DEFAULT_DB_CONNECT_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "DB_CONNECT_TIMEOUT_SECONDS",
            "db_connect_timeout_seconds",
        ),
        gt=0,
    )
    db_pool_size: int = Field(
        default=DEFAULT_DB_POOL_SIZE,
        validation_alias=AliasChoices("DB_POOL_SIZE", "db_pool_size"),
        ge=1,
    )
    db_pool_max_overflow: int = Field(
        default=DEFAULT_DB_POOL_MAX_OVERFLOW,
        validation_alias=AliasChoices("DB_POOL_MAX_OVERFLOW", "db_pool_max_overflow"),
        ge=0,
    )

    list_page_size: int = Field(
        default=DEFAULT_LIST_PAGE_SIZE,
        validation_alias=AliasChoices("LIST_PAGE_SIZE", "list_page_size"),
        gt=0,
    )
    list_max_page_size: int = Field(
        default=DEFAULT_LIST_MAX_PAGE_SIZE,
        validation_alias=AliasChoices("LIST_MAX_PAGE_SIZE", "list_max_page_size"),
        gt=0,
    )
    mask_media_paths: bool = Field(
        default=DEFAULT_MASK_MEDIA_PATHS,
        validation_alias=AliasChoices("MASK_MEDIA_PATHS", "mask_media_paths"),
    )
    mask_message_text: bool = Field(
        default=DEFAULT_MASK_MESSAGE_TEXT,
        validation_alias=AliasChoices("MASK_MESSAGE_TEXT", "mask_message_text"),
    )
    enable_auth_db_enrichment: bool = Field(
        default=DEFAULT_ENABLE_AUTH_DB_ENRICHMENT,
        validation_alias=AliasChoices(
            "ENABLE_AUTH_DB_ENRICHMENT",
            "enable_auth_db_enrichment",
        ),
    )

    log_level: str = Field(
        default=DEFAULT_LOG_LEVEL,
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
    )
    allowed_origins: str = Field(
        default=DEFAULT_ALLOWED_ORIGINS,
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "allowed_origins"),
        description="Comma-separated CORS origins; empty disables CORS middleware.",
    )

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper()

    def allowed_origins_list(self) -> list[str]:
        if not self.allowed_origins.strip():
            return []
        return [part.strip() for part in self.allowed_origins.split(",") if part.strip()]


try:
    settings = Settings()
except ValidationError as exc:
    for error in exc.errors():
        field = error["loc"][0] if error["loc"] else "unknown"
        annotation = Settings.model_fields[str(field)].annotation if str(field) in Settings.model_fields else None
        if error["type"] == "missing" and annotation is not None and _is_optional_string(annotation):
            continue
        print(f"Configuration error: {error['msg']} ({field})", file=sys.stderr)
    raise SystemExit(1) from exc
