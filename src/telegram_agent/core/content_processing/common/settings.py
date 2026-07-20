"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any,  get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.content_processing.common.const import DEFAULT_SQLALCHEMY_DATABASE_URL, \
    DEFAULT_ALLOWED_ORIGINS, \
    DEFAULT_TELEGRAM_AUTH_BASE_URL, DEFAULT_REDIS_URL, DEFAULT_MEDIA_STORAGE_ROOT, \
    DEFAULT_TELEGRAM_API_BASE_URL, DEFAULT_WHISPERX_BASE_URL, DEFAULT_MEDIA_DOWNLOAD_MAX_BYTES, \
    DEFAULT_MEDIA_DOWNLOAD_CHUNK_SIZE, DEFAULT_MEDIA_HTTP_CONNECT_TIMEOUT_SECONDS, \
    DEFAULT_MEDIA_HTTP_READ_TIMEOUT_SECONDS, DEFAULT_MEDIA_HTTP_WRITE_TIMEOUT_SECONDS, \
    DEFAULT_MEDIA_HTTP_POOL_TIMEOUT_SECONDS, DEFAULT_MEDIA_PROCESSING_LEASE_SECONDS, \
    DEFAULT_MEDIA_TASK_MAX_RETRIES, DEFAULT_MEDIA_TASK_RETRY_BASE_SECONDS, DEFAULT_FFMPEG_BINARY, \
    DEFAULT_FFMPEG_TIMEOUT_SECONDS, DEFAULT_WHISPERX_MODEL, \
    DEFAULT_WHISPERX_REQUEST_TIMEOUT_SECONDS, DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE, \
    DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS, DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS, \
    DEFAULT_OUTBOX_RETRY_BASE_SECONDS, DEFAULT_OUTBOX_RETRY_MAX_SECONDS, DEFAULT_LOG_LEVEL
from telegram_agent.core.content_processing.common.const import (
    DEFAULT_CALLBACK_TASK_MAX_RETRIES,
    DEFAULT_CALLBACK_TASK_RETRY_BASE_SECONDS,
    DEFAULT_JOB_EXPECTATION_DEFAULT_SECONDS,
    DEFAULT_JOB_EXPECTATION_RESOLVED_RETENTION_SECONDS,
    DEFAULT_JOB_EXPECTATION_SWEEP_BATCH_SIZE,
    DEFAULT_JOB_EXPECTATION_SWEEP_INTERVAL_SECONDS,
    DEFAULT_JOB_EXPECTATION_SWEEP_LEASE_SECONDS,
    DEFAULT_JOB_EXPECTATION_VOICE_VIDEO_NOTE_SECONDS,
    DEFAULT_LLM_GATEWAY_BASE_URL,
    DEFAULT_LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_ENTRIES,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS_LONG,
    DEFAULT_SUBTITLE_GLOSSARY_OVERLAP_RATIO,
    DEFAULT_SUBTITLE_GLOSSARY_WINDOW_TOKEN_BUDGET,
    DEFAULT_SUBTITLE_TRANSLATION_BATCH_LEASE_SECONDS,
    DEFAULT_SUBTITLE_TRANSLATION_ENABLED,
    DEFAULT_SUBTITLE_TRANSLATION_LOOKAHEAD,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_BATCH_ATTEMPTS,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_SEGMENTS_PER_BATCH,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_SOURCE_TOKENS,
    DEFAULT_SUBTITLE_TRANSLATION_PREVIOUS_CONTEXT,
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

    telegram_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "telegram_bot_token"),
        description="API token for accessing the Telegram bot API.",
    )

    whisperx_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("WHISPERX_SERVICE_TOKEN", "whisperx_service_token"),
        description="API token for accessing the whisperx service API.",
    )

    telegram_api_base_url: str = Field(default=DEFAULT_TELEGRAM_API_BASE_URL, validation_alias=AliasChoices("TELEGRAM_API_BASE_URL", "telegram_api_base_url"))
    media_storage_root: str = Field(default=DEFAULT_MEDIA_STORAGE_ROOT, validation_alias=AliasChoices("MEDIA_STORAGE_ROOT", "media_storage_root"))
    media_download_max_bytes: int = Field(default=DEFAULT_MEDIA_DOWNLOAD_MAX_BYTES, validation_alias=AliasChoices("MEDIA_DOWNLOAD_MAX_BYTES", "media_download_max_bytes"), gt=0)
    media_download_chunk_size: int = Field(default=DEFAULT_MEDIA_DOWNLOAD_CHUNK_SIZE, validation_alias=AliasChoices("MEDIA_DOWNLOAD_CHUNK_SIZE", "media_download_chunk_size"), gt=0)
    media_http_connect_timeout_seconds: float = Field(default=DEFAULT_MEDIA_HTTP_CONNECT_TIMEOUT_SECONDS, validation_alias=AliasChoices("MEDIA_HTTP_CONNECT_TIMEOUT_SECONDS", "media_http_connect_timeout_seconds"), gt=0)
    media_http_read_timeout_seconds: float = Field(default=DEFAULT_MEDIA_HTTP_READ_TIMEOUT_SECONDS, validation_alias=AliasChoices("MEDIA_HTTP_READ_TIMEOUT_SECONDS", "media_http_read_timeout_seconds"), gt=0)
    media_http_write_timeout_seconds: float = Field(default=DEFAULT_MEDIA_HTTP_WRITE_TIMEOUT_SECONDS, validation_alias=AliasChoices("MEDIA_HTTP_WRITE_TIMEOUT_SECONDS", "media_http_write_timeout_seconds"), gt=0)
    media_http_pool_timeout_seconds: float = Field(default=DEFAULT_MEDIA_HTTP_POOL_TIMEOUT_SECONDS, validation_alias=AliasChoices("MEDIA_HTTP_POOL_TIMEOUT_SECONDS", "media_http_pool_timeout_seconds"), gt=0)
    media_processing_lease_seconds: int = Field(default=DEFAULT_MEDIA_PROCESSING_LEASE_SECONDS, validation_alias=AliasChoices("MEDIA_PROCESSING_LEASE_SECONDS", "media_processing_lease_seconds"), gt=0)
    media_task_max_retries: int = Field(default=DEFAULT_MEDIA_TASK_MAX_RETRIES, validation_alias=AliasChoices("MEDIA_TASK_MAX_RETRIES", "media_task_max_retries"), ge=0)
    media_task_retry_base_seconds: int = Field(default=DEFAULT_MEDIA_TASK_RETRY_BASE_SECONDS, validation_alias=AliasChoices("MEDIA_TASK_RETRY_BASE_SECONDS", "media_task_retry_base_seconds"), gt=0)
    ffmpeg_binary: str = Field(
        default=DEFAULT_FFMPEG_BINARY,
        validation_alias=AliasChoices("FFMPEG_BINARY", "ffmpeg_binary"),
        min_length=1,
    )
    ffmpeg_timeout_seconds: float = Field(
        default=DEFAULT_FFMPEG_TIMEOUT_SECONDS,
        validation_alias=AliasChoices("FFMPEG_TIMEOUT_SECONDS", "ffmpeg_timeout_seconds"),
        gt=0,
    )
    whisperx_base_url: str = Field(default=DEFAULT_WHISPERX_BASE_URL, validation_alias=AliasChoices("WHISPERX_BASE_URL", "whisperx_base_url"))
    telegram_ingress_base_url: str = Field(
        default=DEFAULT_TELEGRAM_INGRESS_BASE_URL,
        validation_alias=AliasChoices(
            "TELEGRAM_INGRESS_BASE_URL",
            "telegram_ingress_base_url",
        ),
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
    callback_task_max_retries: int = Field(
        default=DEFAULT_CALLBACK_TASK_MAX_RETRIES,
        validation_alias=AliasChoices("CALLBACK_TASK_MAX_RETRIES", "callback_task_max_retries"),
        ge=0,
    )
    callback_task_retry_base_seconds: int = Field(
        default=DEFAULT_CALLBACK_TASK_RETRY_BASE_SECONDS,
        validation_alias=AliasChoices("CALLBACK_TASK_RETRY_BASE_SECONDS", "callback_task_retry_base_seconds"),
        gt=0,
    )
    whisperx_model: str = Field(default=DEFAULT_WHISPERX_MODEL, validation_alias=AliasChoices("WHISPERX_MODEL", "whisperx_model"), min_length=1)
    whisperx_request_timeout_seconds: float = Field(default=DEFAULT_WHISPERX_REQUEST_TIMEOUT_SECONDS, validation_alias=AliasChoices("WHISPERX_REQUEST_TIMEOUT_SECONDS", "whisperx_request_timeout_seconds"), gt=0)


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
        default=DEFAULT_OUTBOX_DISPATCH_BATCH_SIZE,
        validation_alias=AliasChoices("OUTBOX_DISPATCH_BATCH_SIZE", "outbox_dispatch_batch_size"),
        description="Maximum number of outbox events a dispatcher claims per poll.",
    )

    outbox_dispatch_poll_interval_seconds: float = Field(
        default=DEFAULT_OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS,
        validation_alias=AliasChoices(
            "OUTBOX_DISPATCH_POLL_INTERVAL_SECONDS",
            "outbox_dispatch_poll_interval_seconds",
        ),
        description="Celery Beat polling interval for dispatching outbox events.",
    )

    outbox_dispatch_lease_seconds: int = Field(
        default=DEFAULT_OUTBOX_DISPATCH_LEASE_SECONDS,
        validation_alias=AliasChoices("OUTBOX_DISPATCH_LEASE_SECONDS", "outbox_dispatch_lease_seconds"),
        description="Seconds before an in-flight outbox dispatch lease can be reclaimed.",
    )

    outbox_retry_base_seconds: int = Field(
        default=DEFAULT_OUTBOX_RETRY_BASE_SECONDS,
        validation_alias=AliasChoices("OUTBOX_RETRY_BASE_SECONDS", "outbox_retry_base_seconds"),
        description="Base delay for outbox exponential retry backoff.",
    )

    outbox_retry_max_seconds: int = Field(
        default=DEFAULT_OUTBOX_RETRY_MAX_SECONDS,
        validation_alias=AliasChoices("OUTBOX_RETRY_MAX_SECONDS", "outbox_retry_max_seconds"),
        description="Maximum delay for outbox exponential retry backoff.",
    )

    job_expectation_voice_video_note_seconds: int = Field(
        default=DEFAULT_JOB_EXPECTATION_VOICE_VIDEO_NOTE_SECONDS,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_VOICE_VIDEO_NOTE_SECONDS",
            "job_expectation_voice_video_note_seconds",
        ),
        description="SLA seconds for voice/video_note job completion expectations.",
        gt=0,
    )

    job_expectation_default_seconds: int = Field(
        default=DEFAULT_JOB_EXPECTATION_DEFAULT_SECONDS,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_DEFAULT_SECONDS",
            "job_expectation_default_seconds",
        ),
        description="SLA seconds for non-voice/video_note job completion expectations.",
        gt=0,
    )

    job_expectation_sweep_interval_seconds: float = Field(
        default=DEFAULT_JOB_EXPECTATION_SWEEP_INTERVAL_SECONDS,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_SWEEP_INTERVAL_SECONDS",
            "job_expectation_sweep_interval_seconds",
        ),
        description="Celery Beat interval for sweeping due job completion expectations.",
        gt=0,
    )

    job_expectation_sweep_batch_size: int = Field(
        default=DEFAULT_JOB_EXPECTATION_SWEEP_BATCH_SIZE,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_SWEEP_BATCH_SIZE",
            "job_expectation_sweep_batch_size",
        ),
        description="Maximum open expectations claimed per sweep tick.",
        gt=0,
    )

    job_expectation_sweep_lease_seconds: int = Field(
        default=DEFAULT_JOB_EXPECTATION_SWEEP_LEASE_SECONDS,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_SWEEP_LEASE_SECONDS",
            "job_expectation_sweep_lease_seconds",
        ),
        description="Seconds before a processing expectation lease can be reclaimed.",
        gt=0,
    )

    job_expectation_resolved_retention_seconds: int = Field(
        default=DEFAULT_JOB_EXPECTATION_RESOLVED_RETENTION_SECONDS,
        validation_alias=AliasChoices(
            "JOB_EXPECTATION_RESOLVED_RETENTION_SECONDS",
            "job_expectation_resolved_retention_seconds",
        ),
        description=(
            "Seconds to keep satisfied/timed_out expectations before purge. "
            "0 deletes them on the next sweep."
        ),
        ge=0,
    )

    LOG_LEVEL: str = Field(
        default=DEFAULT_LOG_LEVEL,
        validation_alias=AliasChoices("LOG_LEVEL", "log_level"),
        description="Logging level for the application.",
    )

    llm_gateway_base_url: str = Field(
        default=DEFAULT_LLM_GATEWAY_BASE_URL,
        validation_alias=AliasChoices("LLM_GATEWAY_BASE_URL", "llm_gateway_base_url"),
        description="Base URL for the LLM gateway service API.",
    )
    llm_gateway_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_SERVICE_TOKEN",
            "llm_gateway_service_token",
        ),
        description="API token for accessing the LLM gateway service.",
    )
    llm_gateway_request_timeout_seconds: float = Field(
        default=DEFAULT_LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "LLM_GATEWAY_REQUEST_TIMEOUT_SECONDS",
            "llm_gateway_request_timeout_seconds",
        ),
        gt=0,
    )
    subtitle_translation_enabled: bool = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_ENABLED,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_ENABLED",
            "subtitle_translation_enabled",
        ),
    )
    subtitle_translation_max_source_tokens: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_MAX_SOURCE_TOKENS,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_MAX_SOURCE_TOKENS",
            "subtitle_translation_max_source_tokens",
        ),
        gt=0,
    )
    subtitle_translation_max_segments_per_batch: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_MAX_SEGMENTS_PER_BATCH,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_MAX_SEGMENTS_PER_BATCH",
            "subtitle_translation_max_segments_per_batch",
        ),
        gt=0,
    )
    subtitle_translation_previous_context: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_PREVIOUS_CONTEXT,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_PREVIOUS_CONTEXT",
            "subtitle_translation_previous_context",
        ),
        ge=0,
    )
    subtitle_translation_lookahead: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_LOOKAHEAD,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_LOOKAHEAD",
            "subtitle_translation_lookahead",
        ),
        ge=0,
    )
    subtitle_glossary_max_windows: int = Field(
        default=DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS,
        validation_alias=AliasChoices(
            "SUBTITLE_GLOSSARY_MAX_WINDOWS",
            "subtitle_glossary_max_windows",
        ),
        gt=0,
    )
    subtitle_glossary_max_windows_long: int = Field(
        default=DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS_LONG,
        validation_alias=AliasChoices(
            "SUBTITLE_GLOSSARY_MAX_WINDOWS_LONG",
            "subtitle_glossary_max_windows_long",
        ),
        gt=0,
    )
    subtitle_glossary_window_token_budget: int = Field(
        default=DEFAULT_SUBTITLE_GLOSSARY_WINDOW_TOKEN_BUDGET,
        validation_alias=AliasChoices(
            "SUBTITLE_GLOSSARY_WINDOW_TOKEN_BUDGET",
            "subtitle_glossary_window_token_budget",
        ),
        gt=0,
    )
    subtitle_glossary_overlap_ratio: float = Field(
        default=DEFAULT_SUBTITLE_GLOSSARY_OVERLAP_RATIO,
        validation_alias=AliasChoices(
            "SUBTITLE_GLOSSARY_OVERLAP_RATIO",
            "subtitle_glossary_overlap_ratio",
        ),
        ge=0,
        lt=0.5,
    )
    subtitle_glossary_max_entries: int = Field(
        default=DEFAULT_SUBTITLE_GLOSSARY_MAX_ENTRIES,
        validation_alias=AliasChoices(
            "SUBTITLE_GLOSSARY_MAX_ENTRIES",
            "subtitle_glossary_max_entries",
        ),
        gt=0,
    )
    subtitle_translation_batch_lease_seconds: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_BATCH_LEASE_SECONDS,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_BATCH_LEASE_SECONDS",
            "subtitle_translation_batch_lease_seconds",
        ),
        gt=0,
    )
    subtitle_translation_max_batch_attempts: int = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_MAX_BATCH_ATTEMPTS,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_MAX_BATCH_ATTEMPTS",
            "subtitle_translation_max_batch_attempts",
        ),
        gt=0,
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
