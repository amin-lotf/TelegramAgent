from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from starlette import status

from telegram_agent.core.common.exceptions import WhisperXBackendBusyError
from telegram_agent.core.whisperx.api.v1.transcriptions.dependencies import get_whisperx_runtime
from telegram_agent.core.whisperx.api.v1.transcriptions.schemas import WhisperXTranscriptResponse, \
    WhisperXTranscriptSegmentResponse
from telegram_agent.core.whisperx.runtime import WhisperXRuntime

router = APIRouter(
    prefix="/audio",
    tags=["whisperx"],
)


@router.post(
    "/transcriptions",
    response_model=WhisperXTranscriptResponse,
    status_code=status.HTTP_200_OK,
)
async def create_transcription(
    file: UploadFile = File(...),
    model: str = Form(...),
    response_format: str = Form("verbose_json"),
    language: str | None = Form(default=None),
    temperature: float = Form(default=0.0),
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
    runtime: WhisperXRuntime = Depends(get_whisperx_runtime),
) -> WhisperXTranscriptResponse:
    del temperature
    del x_request_id

    if response_format != "verbose_json":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only response_format=verbose_json is supported",
        )

    if model.strip() != runtime.model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported model: {model}",
        )

    suffix = Path(file.filename or "audio").suffix

    with tempfile.NamedTemporaryFile(
        prefix="whisperx-upload-",
        suffix=suffix,
        delete=False,
    ) as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        temp_path = Path(temp_file.name)

    try:
        transcript = await runtime.transcribe(
            audio_path=temp_path,
         language=language,
        )
    finally:
        await file.close()
        temp_path.unlink(missing_ok=True)

    return WhisperXTranscriptResponse(
        text=transcript.text,
        segments=[
            WhisperXTranscriptSegmentResponse(
                start=segment.start_seconds,
                end=segment.end_seconds,
                text=segment.text,
                language=segment.language,
                language_probability=segment.language_probability,
                speaker=segment.speaker,
                speaker_confidence=segment.speaker_confidence,
            )
            for segment in transcript.segments
        ],
        language=transcript.language,
        language_probability=transcript.language_probability,
        duration=transcript.duration_seconds,
        model=runtime.model_name,
    )
