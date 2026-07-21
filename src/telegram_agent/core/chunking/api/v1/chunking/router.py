from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from starlette import status

from telegram_agent.core.common.api.security.token_verification import VerifyApiToken
from telegram_agent.core.chunking.api.v1.chunking.dependencies import (
    get_transcript_chunking_service,
)
from telegram_agent.core.chunking.api.v1.chunking.schemas import (
    ChunkResponse,
    ChunkTranscriptRequest,
    ChunkTranscriptResponse,
)
from telegram_agent.core.chunking.common.commands import (
    ChunkingOptions,
    ChunkTranscriptCommand,
    TranscriptSegmentInput,
)
from telegram_agent.core.chunking.common.settings import settings
from telegram_agent.core.chunking.services.transcript_chunking import TranscriptChunkingService

router = APIRouter(
    prefix="/chunking",
    tags=["chunking"],
    dependencies=[Depends(VerifyApiToken(settings.chunking_service_token))],
)


@router.post(
    "/transcripts",
    response_model=ChunkTranscriptResponse,
    status_code=status.HTTP_200_OK,
)
async def chunk_transcript(
    payload: ChunkTranscriptRequest,
    service: TranscriptChunkingService = Depends(get_transcript_chunking_service),
) -> ChunkTranscriptResponse:
    for segment in payload.segments:
        if segment.end_ms < segment.start_ms:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Segment {segment.segment_index} has end_ms < start_ms"
                ),
            )

    options_payload = payload.options
    options = ChunkingOptions(
        target_chunk_duration_ms=(
            options_payload.target_chunk_duration_ms
            if options_payload and options_payload.target_chunk_duration_ms is not None
            else settings.target_chunk_duration_ms
        ),
        max_chunk_chars=(
            options_payload.max_chunk_chars
            if options_payload and options_payload.max_chunk_chars is not None
            else settings.max_chunk_chars
        ),
        max_chunk_tokens=(
            options_payload.max_chunk_tokens
            if options_payload and options_payload.max_chunk_tokens is not None
            else settings.max_chunk_tokens
        ),
        overlap_duration_ms=(
            options_payload.overlap_duration_ms
            if options_payload and options_payload.overlap_duration_ms is not None
            else settings.overlap_duration_ms
        ),
        overlap_segments=(
            options_payload.overlap_segments
            if options_payload and options_payload.overlap_segments is not None
            else settings.overlap_segments
        ),
    )

    command = ChunkTranscriptCommand(
        language=payload.language,
        duration_ms=payload.duration_ms,
        segments=tuple(
            TranscriptSegmentInput(
                segment_index=segment.segment_index,
                start_ms=segment.start_ms,
                end_ms=segment.end_ms,
                text=segment.text,
                speaker=segment.speaker,
                speaker_confidence=segment.speaker_confidence,
            )
            for segment in payload.segments
        ),
        options=options,
    )
    result = service.chunk_transcript(command)
    return ChunkTranscriptResponse(
        content_type=result.content_type,
        strategy=result.strategy,
        chunk_count=result.chunk_count,
        chunks=[
            ChunkResponse(
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                start_ms=chunk.start_ms,
                end_ms=chunk.end_ms,
                char_count=chunk.char_count,
                token_count=chunk.token_count,
                segment_index_start=chunk.segment_index_start,
                segment_index_end=chunk.segment_index_end,
                speakers=list(chunk.speakers),
            )
            for chunk in result.chunks
        ],
    )
