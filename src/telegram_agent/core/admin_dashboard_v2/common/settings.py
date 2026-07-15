from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.admin_dashboard_v2.security.passwords import (
    normalize_password_hash,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    telegram_ingress_read_database_url: SecretStr = Field(
        validation_alias=AliasChoices(
            "TELEGRAM_INGRESS_READ_DATABASE_URL",
            "telegram_ingress_read_database_url",
        )
    )
    content_processing_read_database_url: SecretStr = Field(
        validation_alias=AliasChoices(
            "CONTENT_PROCESSING_READ_DATABASE_URL",
            "content_processing_read_database_url",
        )
    )
    agent_runtime_read_database_url: SecretStr = Field(
        validation_alias=AliasChoices(
            "AGENT_RUNTIME_READ_DATABASE_URL",
            "agent_runtime_read_database_url",
        )
    )
    telegram_auth_read_database_url: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "TELEGRAM_AUTH_READ_DATABASE_URL",
            "telegram_auth_read_database_url",
        ),
    )

    admin_username: str = Field(
        min_length=1,
        validation_alias=AliasChoices("ADMIN_DASHBOARD_V2_USERNAME", "admin_username"),
    )
    admin_password_hash: SecretStr = Field(
        validation_alias=AliasChoices(
            "ADMIN_DASHBOARD_V2_PASSWORD_HASH",
            "admin_password_hash",
        )
    )
    cursor_secret: SecretStr = Field(
        min_length=32,
        validation_alias=AliasChoices(
            "ADMIN_DASHBOARD_V2_CURSOR_SECRET",
            "cursor_secret",
        ),
    )
    auth_realm: str = Field(default="TelegramAgent operations")

    database_pool_size: int = Field(default=2, ge=1, le=10, validation_alias=AliasChoices("DATABASE_POOL_SIZE", "database_pool_size"))
    database_max_overflow: int = Field(default=0, ge=0, le=10, validation_alias=AliasChoices("DATABASE_MAX_OVERFLOW", "database_max_overflow"))
    database_pool_timeout_seconds: float = Field(default=1.0, gt=0, le=30, validation_alias=AliasChoices("DATABASE_POOL_TIMEOUT_SECONDS", "database_pool_timeout_seconds"))
    database_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=30, validation_alias=AliasChoices("DATABASE_CONNECT_TIMEOUT_SECONDS", "database_connect_timeout_seconds"))
    database_statement_timeout_ms: int = Field(default=3000, ge=100, le=30000, validation_alias=AliasChoices("DATABASE_STATEMENT_TIMEOUT_MS", "database_statement_timeout_ms"))

    default_page_size: int = Field(default=30, ge=1, le=100, validation_alias=AliasChoices("DEFAULT_PAGE_SIZE", "default_page_size"))
    maximum_page_size: int = Field(default=100, ge=1, le=250, validation_alias=AliasChoices("MAXIMUM_PAGE_SIZE", "maximum_page_size"))
    listing_chunk_size: int = Field(default=100, ge=10, le=500, validation_alias=AliasChoices("LISTING_CHUNK_SIZE", "listing_chunk_size"))
    listing_scan_limit: int = Field(default=2000, ge=100, le=10000, validation_alias=AliasChoices("LISTING_SCAN_LIMIT", "listing_scan_limit"))
    maximum_content_attempts: int = Field(default=20, ge=1, le=100, validation_alias=AliasChoices("MAXIMUM_CONTENT_ATTEMPTS", "maximum_content_attempts"))
    maximum_media_assets: int = Field(default=200, ge=1, le=2000, validation_alias=AliasChoices("MAXIMUM_MEDIA_ASSETS", "maximum_media_assets"))
    maximum_outbox_events: int = Field(default=100, ge=1, le=500, validation_alias=AliasChoices("MAXIMUM_OUTBOX_EVENTS", "maximum_outbox_events"))
    maximum_group_siblings: int = Field(default=100, ge=1, le=500, validation_alias=AliasChoices("MAXIMUM_GROUP_SIBLINGS", "maximum_group_siblings"))
    maximum_transcript_segments: int = Field(default=500, ge=1, le=5000, validation_alias=AliasChoices("MAXIMUM_TRANSCRIPT_SEGMENTS", "maximum_transcript_segments"))
    maximum_raw_json_bytes: int = Field(default=65536, ge=1024, le=1048576, validation_alias=AliasChoices("MAXIMUM_RAW_JSON_BYTES", "maximum_raw_json_bytes"))
    display_timezone: str = Field(default="UTC", min_length=1, validation_alias=AliasChoices("DISPLAY_TIMEZONE", "display_timezone"))
    log_level: str = Field(default="INFO", validation_alias=AliasChoices("LOG_LEVEL", "log_level"))

    @field_validator("admin_password_hash")
    @classmethod
    def validate_password_hash(cls, value: SecretStr) -> SecretStr:
        normalized = normalize_password_hash(value.get_secret_value())
        parts = normalized.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            raise ValueError(
                "ADMIN_DASHBOARD_V2_PASSWORD_HASH must use "
                "pbkdf2_sha256$iterations$salt_b64$digest_b64"
            )
        try:
            iterations = int(parts[1])
        except ValueError as exc:
            raise ValueError("PBKDF2 iteration count must be an integer") from exc
        if iterations < 600_000:
            raise ValueError("PBKDF2 iteration count must be at least 600000")
        return SecretStr(normalized)

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("DISPLAY_TIMEZONE must be a valid IANA timezone") from exc
        return value
