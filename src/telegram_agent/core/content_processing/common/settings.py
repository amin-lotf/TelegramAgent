"""Runtime configuration loaded from environment variables and .env."""
import sys
from typing import Any, Literal, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.content_processing.common.const import DEFAULT_SQLALCHEMY_DATABASE_URL, \
    DEFAULT_ALLOWED_ORIGINS, \
    DEFAULT_TELEGRAM_AUTH_BASE_URL, DEFAULT_REDIS_URL, DEFAULT_MEDIA_STORAGE_ROOT, \
    DEFAULT_TELEGRAM_API_BASE_URL, DEFAULT_MEDIA_DOWNLOAD_MAX_BYTES, \
    DEFAULT_MEDIA_DOWNLOAD_CHUNK_SIZE, DEFAULT_MEDIA_HTTP_CONNECT_TIMEOUT_SECONDS, \
    DEFAULT_MEDIA_HTTP_READ_TIMEOUT_SECONDS, DEFAULT_MEDIA_HTTP_WRITE_TIMEOUT_SECONDS, \
    DEFAULT_MEDIA_HTTP_POOL_TIMEOUT_SECONDS, DEFAULT_MEDIA_PROCESSING_LEASE_SECONDS, \
    DEFAULT_MEDIA_TASK_MAX_RETRIES, DEFAULT_MEDIA_TASK_RETRY_BASE_SECONDS, DEFAULT_FFMPEG_BINARY, \
    DEFAULT_FFMPEG_TIMEOUT_SECONDS, DEFAULT_FFMPEG_CANCEL_GRACE_SECONDS, DEFAULT_WHISPERX_MODEL, \
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
    DEFAULT_MADLAD_BASE_URL,
    DEFAULT_MADLAD_BEAM_SIZE,
    DEFAULT_MADLAD_CLIENT_BATCH_SIZE,
    DEFAULT_MADLAD_LANGUAGE_PAIRS,
    DEFAULT_MADLAD_MAX_NEW_TOKENS,
    DEFAULT_MADLAD_REQUEST_MAX_ATTEMPTS,
    DEFAULT_MADLAD_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_MADLAD_RETRY_BACKOFF_SECONDS,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_ENTRIES,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS,
    DEFAULT_SUBTITLE_GLOSSARY_MAX_WINDOWS_LONG,
    DEFAULT_SUBTITLE_GLOSSARY_OVERLAP_RATIO,
    DEFAULT_SUBTITLE_GLOSSARY_WINDOW_TOKEN_BUDGET,
    DEFAULT_SUBTITLE_TRANSLATION_BACKEND,
    DEFAULT_SUBTITLE_TRANSLATION_BATCH_LEASE_SECONDS,
    DEFAULT_SUBTITLE_TRANSLATION_ENABLED,
    DEFAULT_SUBTITLE_TRANSLATION_LOOKAHEAD,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_BATCH_ATTEMPTS,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_SEGMENTS_PER_BATCH,
    DEFAULT_SUBTITLE_TRANSLATION_MAX_SOURCE_TOKENS,
    DEFAULT_SUBTITLE_TRANSLATION_PREVIOUS_CONTEXT,
    DEFAULT_TELEGRAM_INGRESS_BASE_URL,
    DEFAULT_TELEGRAM_INGRESS_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_GPU_EXECUTION_BASE_URL,
    DEFAULT_GPU_EXECUTION_HTTP_TIMEOUT_SECONDS,
    DEFAULT_GPU_EXECUTION_JOB_MAX_ATTEMPTS,
    DEFAULT_GPU_EXECUTION_JOB_MAX_TIMEOUT_SECONDS,
    DEFAULT_GPU_EXECUTION_POLL_INTERVAL_SECONDS,
    DEFAULT_GPU_EXECUTION_WAIT_TIMEOUT_SECONDS,
    DEFAULT_COSYVOICE_MODEL,
    DEFAULT_COSYVOICE_INFERENCE_MODE,
    DEFAULT_COSYVOICE_PROMPT_PREFIX,
    DEFAULT_COSYVOICE_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_COSYVOICE_SHORT_TEXT_SPEED,
    DEFAULT_COSYVOICE_SHORT_TEXT_MAX_ATTEMPTS,
    DEFAULT_COSYVOICE_DURATION_FIT_MAX_SPEED,
    DEFAULT_COSYVOICE_DURATION_FIT_TARGET_RATIO,
    DEFAULT_COSYVOICE_MAX_IN_FLIGHT_SEGMENTS,
    DEFAULT_COSYVOICE_MAX_IN_FLIGHT_SEGMENTS_LIMIT,
    DEFAULT_SAM_AUDIO_MODEL,
    DEFAULT_SAM_AUDIO_REQUEST_TIMEOUT_SECONDS,
    DEFAULT_SAM_AUDIO_DESCRIPTION,
    DEFAULT_SAM_AUDIO_CHUNK_SECONDS,
    DEFAULT_SAM_AUDIO_OVERLAP_SECONDS,
    DEFAULT_DUBBING_GPU_MAX_ATTEMPTS,
    DEFAULT_DUBBING_BACKGROUND_RELATIVE_DB,
    DEFAULT_DUBBING_SAMPLE_RATE,
    DEFAULT_DUBBING_CHANNELS,
    DEFAULT_DUBBING_FADE_MILLISECONDS,
    DEFAULT_DUBBING_AUDIO_BITRATE,
)
from telegram_agent.core.content_processing.common.language_codes import (
    parse_madlad_language_pairs,
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

    gpu_execution_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_SERVICE_TOKEN",
            "gpu_execution_service_token",
        ),
        description="API token for the central GPU execution service.",
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
    ffmpeg_cancel_grace_seconds: float = Field(
        default=DEFAULT_FFMPEG_CANCEL_GRACE_SECONDS,
        validation_alias=AliasChoices(
            "FFMPEG_CANCEL_GRACE_SECONDS", "ffmpeg_cancel_grace_seconds"
        ),
        gt=0,
    )
    gpu_execution_base_url: str = Field(
        default=DEFAULT_GPU_EXECUTION_BASE_URL,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_BASE_URL",
            "gpu_execution_base_url",
        ),
    )
    gpu_execution_http_timeout_seconds: float = Field(
        default=DEFAULT_GPU_EXECUTION_HTTP_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_HTTP_TIMEOUT_SECONDS",
            "gpu_execution_http_timeout_seconds",
        ),
        gt=0,
    )
    gpu_execution_poll_interval_seconds: float = Field(
        default=DEFAULT_GPU_EXECUTION_POLL_INTERVAL_SECONDS,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_POLL_INTERVAL_SECONDS",
            "gpu_execution_poll_interval_seconds",
        ),
        gt=0,
    )
    gpu_execution_wait_timeout_seconds: float = Field(
        default=DEFAULT_GPU_EXECUTION_WAIT_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_WAIT_TIMEOUT_SECONDS",
            "gpu_execution_wait_timeout_seconds",
        ),
        gt=0,
    )
    gpu_execution_job_max_attempts: int = Field(
        default=DEFAULT_GPU_EXECUTION_JOB_MAX_ATTEMPTS,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_JOB_MAX_ATTEMPTS",
            "gpu_execution_job_max_attempts",
        ),
        ge=1,
    )
    gpu_execution_job_max_timeout_seconds: int = Field(
        default=DEFAULT_GPU_EXECUTION_JOB_MAX_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_JOB_MAX_TIMEOUT_SECONDS",
            "gpu_execution_job_max_timeout_seconds",
        ),
        gt=0,
    )
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
    subtitle_translation_backend: Literal["openai", "local"] = Field(
        default=DEFAULT_SUBTITLE_TRANSLATION_BACKEND,
        validation_alias=AliasChoices(
            "SUBTITLE_TRANSLATION_BACKEND",
            "subtitle_translation_backend",
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

    madlad_language_pairs: str = Field(
        default=DEFAULT_MADLAD_LANGUAGE_PAIRS,
        validation_alias=AliasChoices(
            "MADLAD_LANGUAGE_PAIRS", "madlad_language_pairs"
        ),
        description="Comma-separated source:target pairs routed to local MADLAD.",
    )
    madlad_base_url: str = Field(
        default=DEFAULT_MADLAD_BASE_URL,
        validation_alias=AliasChoices("MADLAD_BASE_URL", "madlad_base_url"),
        min_length=1,
    )
    madlad_request_timeout_seconds: float = Field(
        default=DEFAULT_MADLAD_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "MADLAD_REQUEST_TIMEOUT_SECONDS", "madlad_request_timeout_seconds"
        ),
        gt=0,
    )
    madlad_request_max_attempts: int = Field(
        default=DEFAULT_MADLAD_REQUEST_MAX_ATTEMPTS,
        validation_alias=AliasChoices(
            "MADLAD_REQUEST_MAX_ATTEMPTS", "madlad_request_max_attempts"
        ),
        gt=0,
    )
    madlad_retry_backoff_seconds: float = Field(
        default=DEFAULT_MADLAD_RETRY_BACKOFF_SECONDS,
        validation_alias=AliasChoices(
            "MADLAD_RETRY_BACKOFF_SECONDS", "madlad_retry_backoff_seconds"
        ),
        ge=0,
    )
    madlad_client_batch_size: int = Field(
        default=DEFAULT_MADLAD_CLIENT_BATCH_SIZE,
        validation_alias=AliasChoices(
            "MADLAD_CLIENT_BATCH_SIZE", "madlad_client_batch_size"
        ),
        gt=0,
    )
    madlad_beam_size: int = Field(
        default=DEFAULT_MADLAD_BEAM_SIZE,
        validation_alias=AliasChoices("MADLAD_BEAM_SIZE", "madlad_beam_size"),
        gt=0,
    )
    madlad_max_new_tokens: int = Field(
        default=DEFAULT_MADLAD_MAX_NEW_TOKENS,
        validation_alias=AliasChoices(
            "MADLAD_MAX_NEW_TOKENS", "madlad_max_new_tokens"
        ),
        gt=0,
    )

    cosyvoice_model: str = Field(
        default=DEFAULT_COSYVOICE_MODEL,
        validation_alias=AliasChoices("COSYVOICE_MODEL", "cosyvoice_model"),
        min_length=1,
    )
    cosyvoice_inference_mode: str = Field(
        default=DEFAULT_COSYVOICE_INFERENCE_MODE,
        validation_alias=AliasChoices(
            "COSYVOICE_INFERENCE_MODE", "cosyvoice_inference_mode"
        ),
        pattern="^(cross_lingual|zero_shot)$",
    )
    cosyvoice_prompt_prefix: str = Field(
        default=DEFAULT_COSYVOICE_PROMPT_PREFIX,
        validation_alias=AliasChoices(
            "COSYVOICE_PROMPT_PREFIX", "cosyvoice_prompt_prefix"
        ),
    )
    cosyvoice_request_timeout_seconds: int = Field(
        default=DEFAULT_COSYVOICE_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "COSYVOICE_REQUEST_TIMEOUT_SECONDS", "cosyvoice_request_timeout_seconds"
        ),
        gt=0,
    )
    cosyvoice_short_text_speed: float = Field(
        default=DEFAULT_COSYVOICE_SHORT_TEXT_SPEED,
        validation_alias=AliasChoices(
            "COSYVOICE_SHORT_TEXT_SPEED", "cosyvoice_short_text_speed"
        ),
        gt=0,
    )
    cosyvoice_short_text_max_attempts: int = Field(
        default=DEFAULT_COSYVOICE_SHORT_TEXT_MAX_ATTEMPTS,
        validation_alias=AliasChoices(
            "COSYVOICE_SHORT_TEXT_MAX_ATTEMPTS", "cosyvoice_short_text_max_attempts"
        ),
        gt=0,
    )
    cosyvoice_duration_fit_max_speed: float = Field(
        default=DEFAULT_COSYVOICE_DURATION_FIT_MAX_SPEED,
        validation_alias=AliasChoices(
            "COSYVOICE_DURATION_FIT_MAX_SPEED", "cosyvoice_duration_fit_max_speed"
        ),
        gt=1,
    )
    cosyvoice_duration_fit_target_ratio: float = Field(
        default=DEFAULT_COSYVOICE_DURATION_FIT_TARGET_RATIO,
        validation_alias=AliasChoices(
            "COSYVOICE_DURATION_FIT_TARGET_RATIO", "cosyvoice_duration_fit_target_ratio"
        ),
        gt=0,
        le=1,
    )
    cosyvoice_max_in_flight_segments: int = Field(
        default=DEFAULT_COSYVOICE_MAX_IN_FLIGHT_SEGMENTS,
        validation_alias=AliasChoices(
            "COSYVOICE_MAX_IN_FLIGHT_SEGMENTS",
            "cosyvoice_max_in_flight_segments",
        ),
        gt=0,
        le=DEFAULT_COSYVOICE_MAX_IN_FLIGHT_SEGMENTS_LIMIT,
        description=(
            "Max transcript segments synthesized at once. GPU inference stays "
            "serial in the CosyVoice worker; extra in-flight work overlaps "
            "prompt ffmpeg and duration-fit CPU with the current GPU call."
        ),
    )
    sam_audio_model: str = Field(
        default=DEFAULT_SAM_AUDIO_MODEL,
        validation_alias=AliasChoices("SAM_AUDIO_MODEL", "sam_audio_model"),
        min_length=1,
    )
    sam_audio_request_timeout_seconds: int = Field(
        default=DEFAULT_SAM_AUDIO_REQUEST_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "SAM_AUDIO_REQUEST_TIMEOUT_SECONDS", "sam_audio_request_timeout_seconds"
        ),
        gt=0,
    )
    sam_audio_description: str = Field(
        default=DEFAULT_SAM_AUDIO_DESCRIPTION,
        validation_alias=AliasChoices(
            "SAM_AUDIO_DESCRIPTION", "sam_audio_description"
        ),
        min_length=1,
    )
    sam_audio_chunk_seconds: float = Field(
        default=DEFAULT_SAM_AUDIO_CHUNK_SECONDS,
        validation_alias=AliasChoices(
            "SAM_AUDIO_CHUNK_SECONDS", "sam_audio_chunk_seconds"
        ),
        gt=0,
    )
    sam_audio_overlap_seconds: float = Field(
        default=DEFAULT_SAM_AUDIO_OVERLAP_SECONDS,
        validation_alias=AliasChoices(
            "SAM_AUDIO_OVERLAP_SECONDS", "sam_audio_overlap_seconds"
        ),
        gt=0,
    )
    dubbing_gpu_max_attempts: int = Field(
        default=DEFAULT_DUBBING_GPU_MAX_ATTEMPTS,
        validation_alias=AliasChoices(
            "DUBBING_GPU_MAX_ATTEMPTS", "dubbing_gpu_max_attempts"
        ),
        ge=1,
    )
    dubbing_background_relative_db: float = Field(
        default=DEFAULT_DUBBING_BACKGROUND_RELATIVE_DB,
        validation_alias=AliasChoices(
            "DUBBING_BACKGROUND_RELATIVE_DB", "dubbing_background_relative_db"
        ),
        le=0,
    )
    dubbing_sample_rate: int = Field(
        default=DEFAULT_DUBBING_SAMPLE_RATE,
        validation_alias=AliasChoices("DUBBING_SAMPLE_RATE", "dubbing_sample_rate"),
        gt=0,
    )
    dubbing_channels: int = Field(
        default=DEFAULT_DUBBING_CHANNELS,
        validation_alias=AliasChoices("DUBBING_CHANNELS", "dubbing_channels"),
        ge=1,
        le=2,
    )
    dubbing_fade_milliseconds: int = Field(
        default=DEFAULT_DUBBING_FADE_MILLISECONDS,
        validation_alias=AliasChoices(
            "DUBBING_FADE_MILLISECONDS", "dubbing_fade_milliseconds"
        ),
        ge=0,
    )
    dubbing_audio_bitrate: str = Field(
        default=DEFAULT_DUBBING_AUDIO_BITRATE,
        validation_alias=AliasChoices(
            "DUBBING_AUDIO_BITRATE", "dubbing_audio_bitrate"
        ),
        min_length=1,
    )

    @model_validator(mode="after")
    def _validate_dubbing_settings(self) -> "Settings":
        parse_madlad_language_pairs(self.madlad_language_pairs)
        if self.sam_audio_overlap_seconds >= self.sam_audio_chunk_seconds:
            raise ValueError(
                "SAM_AUDIO_OVERLAP_SECONDS must be shorter than SAM_AUDIO_CHUNK_SECONDS"
            )
        if self.cosyvoice_request_timeout_seconds > self.gpu_execution_job_max_timeout_seconds:
            raise ValueError(
                "COSYVOICE_REQUEST_TIMEOUT_SECONDS cannot exceed GPU execution maximum"
            )
        if self.sam_audio_request_timeout_seconds > self.gpu_execution_job_max_timeout_seconds:
            raise ValueError(
                "SAM_AUDIO_REQUEST_TIMEOUT_SECONDS cannot exceed GPU execution maximum"
            )
        if self.dubbing_gpu_max_attempts > self.gpu_execution_job_max_attempts:
            raise ValueError(
                "DUBBING_GPU_MAX_ATTEMPTS cannot exceed GPU execution maximum"
            )
        return self

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
