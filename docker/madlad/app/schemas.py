from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    model: str
    device: str
    model_ready: bool
    cuda_available: bool = False
    adapter_dir: str | None = None
    adapter_sha256: str | None = None
    adapter_loaded: bool = False


class ReadyResponse(BaseModel):
    ready: bool


class LanguagesResponse(BaseModel):
    aliases: dict[str, str]
    note: str = "Configured adapters determine which language pairs are supported."


class TranslateRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    source_lang: str = ""
    target_lang: str = Field(min_length=1)
    beam_size: int | None = Field(default=None, gt=0)
    max_new_tokens: int | None = Field(default=None, gt=0)


class TranslateResponse(BaseModel):
    translations: list[str]
    source_lang: str | None = None
    target_lang: str
    target_token: str
    model: str
    count: int
    adapter_sha256: str | None = None


class ReloadAdapterResponse(BaseModel):
    reloaded: bool
    adapter_dir: str
    adapter_sha256: str | None = None
