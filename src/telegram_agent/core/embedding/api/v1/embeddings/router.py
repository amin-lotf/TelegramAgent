from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.embedding.api.v1.embeddings.dependencies import (
    get_embedding_service,
)
from telegram_agent.core.embedding.api.v1.embeddings.schemas import (
    EmbedChunksRequest,
    EmbedChunksResponse,
    EmbeddingItemResponse,
)
from telegram_agent.core.embedding.common.commands import (
    ChunkToEmbed,
    EmbedChunksCommand,
    EmbedOptions,
)
from telegram_agent.core.embedding.common.settings import settings
from telegram_agent.core.embedding.services.embedding import EmbeddingService

router = APIRouter(
    prefix="/embeddings",
    tags=["embeddings"],
    dependencies=[Depends(VerifyApiToken(settings.embedding_service_token))],
)


@router.post(
    "",
    response_model=EmbedChunksResponse,
    status_code=status.HTTP_200_OK,
)
async def embed_chunks(
    payload: EmbedChunksRequest,
    service: EmbeddingService = Depends(get_embedding_service),
) -> EmbedChunksResponse:
    if len(payload.chunks) > settings.max_embedding_batch_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Batch size {len(payload.chunks)} exceeds maximum "
                f"{settings.max_embedding_batch_size}"
            ),
        )

    for chunk in payload.chunks:
        if not chunk.text.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Chunk {chunk.chunk_id!r} has empty text",
            )

    options_payload = payload.options
    options = EmbedOptions(
        model=(
            options_payload.model
            if options_payload and options_payload.model is not None
            else settings.embedding_model
        ),
        dimensions=(
            options_payload.dimensions
            if options_payload and options_payload.dimensions is not None
            else settings.embedding_dimensions
        ),
    )

    command = EmbedChunksCommand(
        chunks=tuple(
            ChunkToEmbed(chunk_id=chunk.chunk_id, text=chunk.text)
            for chunk in payload.chunks
        ),
        options=options,
    )
    result = await service.embed_chunks(command)
    return EmbedChunksResponse(
        provider=result.provider,
        model=result.model,
        dimensions=result.dimensions,
        count=result.count,
        embeddings=[
            EmbeddingItemResponse(
                chunk_id=item.chunk_id,
                index=item.index,
                embedding=list(item.embedding),
                dimensions=item.dimensions,
            )
            for item in result.embeddings
        ],
    )
