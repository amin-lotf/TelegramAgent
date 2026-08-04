"""Runtime configuration for the central GPU execution service."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, get_args

from pydantic import AliasChoices, Field, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_optional_string(annotation: Any) -> bool:
    args = get_args(annotation)
    return len(args) == 2 and str in args and type(None) in args


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_parse_none_str="None",
        extra="ignore",
    )

    gpu_execution_service_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "GPU_EXECUTION_SERVICE_TOKEN",
            "gpu_execution_service_token",
        ),
    )
    sqlalchemy_database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_agent",
        validation_alias=AliasChoices(
            "SQLALCHEMY_DATABASE_URL",
            "sqlalchemy_database_url",
        ),
    )
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("REDIS_URL", "redis_url"),
    )
    gpu_shared_storage_root: Path = Field(
        default=Path("/app/media"),
        validation_alias=AliasChoices(
            "GPU_SHARED_STORAGE_ROOT",
            "gpu_shared_storage_root",
        ),
    )
    gpu_job_default_timeout_seconds: int = Field(
        default=14_400,
        validation_alias=AliasChoices(
            "GPU_JOB_DEFAULT_TIMEOUT_SECONDS",
            "gpu_job_default_timeout_seconds",
        ),
        gt=0,
    )
    gpu_job_max_timeout_seconds: int = Field(
        default=86_400,
        validation_alias=AliasChoices(
            "GPU_JOB_MAX_TIMEOUT_SECONDS",
            "gpu_job_max_timeout_seconds",
        ),
        gt=0,
    )
    gpu_job_default_max_attempts: int = Field(
        default=3,
        validation_alias=AliasChoices(
            "GPU_JOB_DEFAULT_MAX_ATTEMPTS",
            "gpu_job_default_max_attempts",
        ),
        ge=1,
    )
    gpu_job_max_attempts: int = Field(
        default=10,
        validation_alias=AliasChoices(
            "GPU_JOB_MAX_ATTEMPTS",
            "gpu_job_max_attempts",
        ),
        ge=1,
    )
    gpu_job_lease_seconds: int = Field(
        default=120,
        validation_alias=AliasChoices(
            "GPU_JOB_LEASE_SECONDS",
            "gpu_job_lease_seconds",
        ),
        gt=10,
    )
    gpu_job_heartbeat_seconds: float = Field(
        default=5.0,
        validation_alias=AliasChoices(
            "GPU_JOB_HEARTBEAT_SECONDS",
            "gpu_job_heartbeat_seconds",
        ),
        gt=0,
    )
    gpu_job_cancel_grace_seconds: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "GPU_JOB_CANCEL_GRACE_SECONDS",
            "gpu_job_cancel_grace_seconds",
        ),
        gt=0,
    )
    gpu_job_retry_base_seconds: int = Field(
        default=15,
        validation_alias=AliasChoices(
            "GPU_JOB_RETRY_BASE_SECONDS",
            "gpu_job_retry_base_seconds",
        ),
        gt=0,
    )
    gpu_outbox_poll_interval_seconds: float = Field(
        default=2.0,
        validation_alias=AliasChoices(
            "GPU_OUTBOX_POLL_INTERVAL_SECONDS",
            "gpu_outbox_poll_interval_seconds",
        ),
        gt=0,
    )
    gpu_recovery_poll_interval_seconds: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "GPU_RECOVERY_POLL_INTERVAL_SECONDS",
            "gpu_recovery_poll_interval_seconds",
        ),
        gt=0,
    )
    gpu_outbox_lease_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices(
            "GPU_OUTBOX_LEASE_SECONDS",
            "gpu_outbox_lease_seconds",
        ),
        gt=0,
    )
    gpu_outbox_batch_size: int = Field(
        default=50,
        validation_alias=AliasChoices(
            "GPU_OUTBOX_BATCH_SIZE",
            "gpu_outbox_batch_size",
        ),
        gt=0,
    )
    LOG_LEVEL: str = "INFO"

    @model_validator(mode="after")
    def _validate_limits(self) -> "Settings":
        if self.gpu_job_default_timeout_seconds > self.gpu_job_max_timeout_seconds:
            raise ValueError(
                "GPU_JOB_DEFAULT_TIMEOUT_SECONDS cannot exceed GPU_JOB_MAX_TIMEOUT_SECONDS"
            )
        if self.gpu_job_default_max_attempts > self.gpu_job_max_attempts:
            raise ValueError(
                "GPU_JOB_DEFAULT_MAX_ATTEMPTS cannot exceed GPU_JOB_MAX_ATTEMPTS"
            )
        if self.gpu_job_heartbeat_seconds >= self.gpu_job_lease_seconds:
            raise ValueError(
                "GPU_JOB_HEARTBEAT_SECONDS must be shorter than GPU_JOB_LEASE_SECONDS"
            )
        return self

    @model_validator(mode="before")
    @classmethod
    def _blank_optional_strings_to_none(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        for field_name, field_info in cls.model_fields.items():
            if _is_optional_string(field_info.annotation):
                value = normalized.get(field_name)
                if isinstance(value, str) and not value.strip():
                    normalized[field_name] = None
        return normalized


def load_settings_or_die() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        print("[CONFIG ERROR] Invalid GPU execution configuration:", file=sys.stderr)
        for error in exc.errors():
            location = ".".join(str(item) for item in error.get("loc", []))
            print(f"  - {location}: {error.get('msg', 'invalid value')}", file=sys.stderr)
        sys.exit(2)


settings = load_settings_or_die()
