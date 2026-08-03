from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from starlette import status

from telegram_agent.core.sensevoice.api.v1.emotions.dependencies import (
    get_sensevoice_runtime,
)
from telegram_agent.core.sensevoice.api.v1.emotions.schemas import (
    SenseVoiceEmotionResponse,
)
from telegram_agent.core.sensevoice.runtime import SenseVoiceRuntime

router = APIRouter(
    prefix="/audio",
    tags=["sensevoice"],
)


@router.post(
    "/emotions",
    response_model=SenseVoiceEmotionResponse,
    status_code=status.HTTP_200_OK,
)
async def create_emotion_extraction(
    file: UploadFile = File(...),
    model: str = Form(...),
    language: str | None = Form(default=None),
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
    runtime: SenseVoiceRuntime = Depends(get_sensevoice_runtime),
) -> SenseVoiceEmotionResponse:
    del x_request_id

    if model.strip() != runtime.model_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported model: {model}",
        )

    suffix = Path(file.filename or "audio").suffix

    with tempfile.NamedTemporaryFile(
        prefix="sensevoice-upload-",
        suffix=suffix,
        delete=False,
    ) as temp_file:
        shutil.copyfileobj(file.file, temp_file)
        temp_path = Path(temp_file.name)

    try:
        result = await runtime.extract_emotion(
            audio_path=temp_path,
            language=language,
        )
    finally:
        await file.close()
        temp_path.unlink(missing_ok=True)

    return SenseVoiceEmotionResponse(
        emotion=result.emotion,
        events=list(result.events),
        language=result.language,
        text=result.text,
        model=runtime.model_name,
    )
