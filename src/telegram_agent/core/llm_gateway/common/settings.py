"""LLM gateway configuration loaded from environment variables and .env."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from telegram_agent.core.llm_gateway.common.const import (
    DEFAULT_DOWNLOAD_AGENT_BACKEND,
    DEFAULT_DOWNLOAD_AGENT_LOCAL_JOB_MAX_ATTEMPTS,
    DEFAULT_DOWNLOAD_AGENT_LOCAL_JOB_TIMEOUT_SECONDS,
    DEFAULT_DOWNLOAD_AGENT_LOCAL_MAX_NEW_TOKENS,
    DEFAULT_DOWNLOAD_AGENT_LOCAL_MAX_VALIDATION_ATTEMPTS,
    DEFAULT_DOWNLOAD_AGENT_LOCAL_MODEL,
    DEFAULT_GPU_EXECUTION_BASE_URL,
    DEFAULT_GPU_EXECUTION_HTTP_TIMEOUT_SECONDS,
    DEFAULT_GPU_EXECUTION_POLL_INTERVAL_SECONDS,
    DEFAULT_GPU_EXECUTION_WAIT_TIMEOUT_SECONDS,
    DEFAULT_GPU_SHARED_STORAGE_ROOT,
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
    download_agent_backend: Literal["openai", "local"] = Field(
        default=DEFAULT_DOWNLOAD_AGENT_BACKEND,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_BACKEND",
            "download_agent_backend",
        ),
    )
    download_agent_local_model: str = Field(
        default=DEFAULT_DOWNLOAD_AGENT_LOCAL_MODEL,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_LOCAL_MODEL",
            "download_agent_local_model",
        ),
        min_length=1,
    )
    download_agent_local_max_validation_attempts: int = Field(
        default=DEFAULT_DOWNLOAD_AGENT_LOCAL_MAX_VALIDATION_ATTEMPTS,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_LOCAL_MAX_VALIDATION_ATTEMPTS",
            "download_agent_local_max_validation_attempts",
        ),
        ge=1,
        le=8,
    )
    download_agent_local_max_new_tokens: int = Field(
        default=DEFAULT_DOWNLOAD_AGENT_LOCAL_MAX_NEW_TOKENS,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_LOCAL_MAX_NEW_TOKENS",
            "download_agent_local_max_new_tokens",
        ),
        ge=32,
        le=4096,
    )
    download_agent_local_job_timeout_seconds: int = Field(
        default=DEFAULT_DOWNLOAD_AGENT_LOCAL_JOB_TIMEOUT_SECONDS,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_LOCAL_JOB_TIMEOUT_SECONDS",
            "download_agent_local_job_timeout_seconds",
        ),
        gt=0,
    )
    download_agent_local_job_max_attempts: int = Field(
        default=DEFAULT_DOWNLOAD_AGENT_LOCAL_JOB_MAX_ATTEMPTS,
        validation_alias=AliasChoices(
            "DOWNLOAD_AGENT_LOCAL_JOB_MAX_ATTEMPTS",
            "download_agent_local_job_max_attempts",
        ),
        ge=1,
        le=10,
    )
    gpu_execution_base_url: str = Field(
        default=DEFAULT_GPU_EXECUTION_BASE_URL,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_BASE_URL",
            "gpu_execution_base_url",
        ),
    )
    gpu_execution_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_SERVICE_TOKEN",
            "gpu_execution_service_token",
        ),
    )
    gpu_shared_storage_root: Path = Field(
        default=Path(DEFAULT_GPU_SHARED_STORAGE_ROOT),
        validation_alias=AliasChoices(
            "GPU_SHARED_STORAGE_ROOT",
            "gpu_shared_storage_root",
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
    LOG_LEVEL: str = Field(default="INFO")

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "llm_gateway_service_token",
        "gpu_execution_service_token",
    )
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
