"""Runtime settings for the MADLAD container."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    madlad_model_id: str = Field(
        default="google/madlad400-3b-mt", validation_alias="MADLAD_MODEL_ID"
    )
    madlad_adapter_dir: str = Field(
        default="/adapters", validation_alias="MADLAD_ADAPTER_DIR"
    )
    madlad_device: Literal["cuda", "cpu", "auto"] = Field(
        default="auto", validation_alias="MADLAD_DEVICE"
    )
    madlad_max_batch_size: int = Field(
        default=8, validation_alias="MADLAD_MAX_BATCH_SIZE", gt=0
    )
    madlad_beam_size: int = Field(
        default=4, validation_alias="MADLAD_BEAM_SIZE", gt=0
    )
    madlad_max_new_tokens: int = Field(
        default=256, validation_alias="MADLAD_MAX_NEW_TOKENS", gt=0
    )
    madlad_max_source_length: int = Field(
        default=256, validation_alias="MADLAD_MAX_SOURCE_LENGTH", gt=0
    )
    madlad_max_input_chars: int = Field(
        default=4000, validation_alias="MADLAD_MAX_INPUT_CHARS", gt=0
    )
    madlad_gpu_concurrency: int = Field(
        default=1, validation_alias="MADLAD_GPU_CONCURRENCY", gt=0
    )
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    skip_model_load: bool = Field(
        default=False,
        validation_alias="SKIP_MODEL_LOAD",
        description="Tests only: start the API without loading model weights.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
