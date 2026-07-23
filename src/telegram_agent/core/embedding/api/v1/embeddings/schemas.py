from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ChunkToEmbedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class EmbedOptionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1)
    dimensions: int | None = Field(default=None, gt=0)


class EmbedChunksRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunks: list[ChunkToEmbedRequest] = Field(..., min_length=1)
    options: EmbedOptionsRequest | None = None


class EmbeddingItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    index: int
    embedding: list[float]
    dimensions: int


class EmbedChunksResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    dimensions: int
    count: int
    embeddings: list[EmbeddingItemResponse]
