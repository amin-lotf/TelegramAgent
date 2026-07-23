from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from telegram_agent.core.embedding.api.v1.embeddings.dependencies import (
    get_embedding_service,
)
from telegram_agent.core.embedding.api.v1.fastapi_app import create_app
from telegram_agent.core.embedding.common.commands import EmbedChunksCommand
from telegram_agent.core.embedding.common.exceptions import RetryableEmbeddingError
from telegram_agent.core.embedding.common.results import (
    EmbedChunksResult,
    EmbeddingItemResult,
)
from tests.support.fastapi import set_expected_api_token


class StubEmbeddingService:
    def __init__(
        self,
        *,
        fail_with: Exception | None = None,
    ) -> None:
        self.commands: list[EmbedChunksCommand] = []
        self._fail_with = fail_with

    async def embed_chunks(self, command: EmbedChunksCommand) -> EmbedChunksResult:
        self.commands.append(command)
        if self._fail_with is not None:
            raise self._fail_with
        return EmbedChunksResult(
            provider="stub",
            model=command.options.model,
            dimensions=2,
            count=len(command.chunks),
            embeddings=tuple(
                EmbeddingItemResult(
                    chunk_id=chunk.chunk_id,
                    index=index,
                    embedding=(float(index), float(index + 1)),
                    dimensions=2,
                )
                for index, chunk in enumerate(command.chunks)
            ),
        )


def _payload(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "chunks": [
            {"chunk_id": "chunk-1", "text": "hello"},
            {"chunk_id": "chunk-2", "text": "world"},
        ],
    }
    body.update(overrides)
    return body


@pytest.mark.asyncio
async def test_embeddings_requires_authentication() -> None:
    app = create_app()
    set_expected_api_token(app, "embedding-token")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/v1/embeddings", json=_payload())

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_embeddings_returns_vectors() -> None:
    app = create_app()
    set_expected_api_token(app, "embedding-token")
    service = StubEmbeddingService()

    async def override_service() -> StubEmbeddingService:
        return service

    app.dependency_overrides[get_embedding_service] = override_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/embeddings",
            headers={"Authorization": "Bearer embedding-token"},
            json=_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stub"
    assert body["count"] == 2
    assert body["dimensions"] == 2
    assert body["embeddings"][0]["chunk_id"] == "chunk-1"
    assert body["embeddings"][0]["embedding"] == [0.0, 1.0]
    assert body["embeddings"][1]["chunk_id"] == "chunk-2"
    assert len(service.commands) == 1
    assert service.commands[0].chunks[0].text == "hello"


@pytest.mark.asyncio
async def test_embeddings_rejects_empty_chunks() -> None:
    app = create_app()
    set_expected_api_token(app, "embedding-token")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/embeddings",
            headers={"Authorization": "Bearer embedding-token"},
            json={"chunks": []},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_retryable_error_maps_to_503() -> None:
    app = create_app()
    set_expected_api_token(app, "embedding-token")
    service = StubEmbeddingService(
        fail_with=RetryableEmbeddingError("temporary"),
    )

    async def override_service() -> StubEmbeddingService:
        return service

    app.dependency_overrides[get_embedding_service] = override_service

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.post(
            "/api/v1/embeddings",
            headers={"Authorization": "Bearer embedding-token"},
            json=_payload(),
        )

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "embedding_unavailable"
    assert body["retryable"] is True


@pytest.mark.asyncio
async def test_health_endpoints() -> None:
    app = create_app()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        health = await client.get("/health")
        root = await client.get("/api")

    assert health.status_code == 200
    assert health.json()["service"] == "embedding"
    assert root.status_code == 200
    assert root.json()["service"] == "embedding"
