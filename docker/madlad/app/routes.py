from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.engine import MadladEngine
from app.languages import UnknownLanguageError, list_aliases, target_language_token
from app.schemas import (
    HealthResponse,
    LanguagesResponse,
    ReadyResponse,
    ReloadAdapterResponse,
    TranslateRequest,
    TranslateResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_engine(request: Request) -> MadladEngine | None:
    return getattr(request.app.state, "engine", None)


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    engine = _get_engine(request)
    return HealthResponse(
        model=settings.madlad_model_id,
        device=engine.device if engine is not None else "unknown",
        model_ready=bool(engine is not None and engine.ready),
        cuda_available=bool(engine.cuda_available) if engine is not None else False,
        adapter_dir=settings.madlad_adapter_dir,
        adapter_sha256=engine.adapter_sha256 if engine is not None else None,
        adapter_loaded=bool(engine.adapter_loaded) if engine is not None else False,
    )


@router.get("/ready", response_model=ReadyResponse)
def ready(request: Request) -> ReadyResponse:
    engine = _get_engine(request)
    return ReadyResponse(ready=bool(engine is not None and engine.ready))


@router.get("/languages", response_model=LanguagesResponse)
def languages() -> LanguagesResponse:
    return LanguagesResponse(aliases=list_aliases())


@router.post("/v1/translate", response_model=TranslateResponse)
def translate(
    request: Request, body: TranslateRequest
) -> TranslateResponse | JSONResponse:
    engine = _get_engine(request)
    if engine is None or not engine.ready:
        return JSONResponse(
            status_code=503,
            content={"code": "model_not_ready", "message": "MADLAD is not ready"},
        )
    try:
        translations = engine.translate_batch(
            body.texts,
            source_lang=body.source_lang or None,
            target_lang=body.target_lang,
            beam_size=body.beam_size,
            max_new_tokens=body.max_new_tokens,
        )
        target = engine.resolve_lang(body.target_lang)
    except UnknownLanguageError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "unknown_language", "message": str(exc)},
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "invalid_request", "message": str(exc)},
        )
    except Exception:
        logger.exception("MADLAD translation failed")
        return JSONResponse(
            status_code=500,
            content={"code": "translation_failed", "message": "Translation failed"},
        )
    source = body.source_lang.strip() or None
    settings = request.app.state.settings
    return TranslateResponse(
        translations=translations,
        source_lang=source,
        target_lang=target,
        target_token=target_language_token(target),
        model=settings.madlad_model_id,
        count=len(translations),
        adapter_sha256=engine.adapter_sha256,
    )


@router.post("/v1/reload-adapter", response_model=ReloadAdapterResponse)
def reload_adapter(request: Request) -> ReloadAdapterResponse | JSONResponse:
    engine = _get_engine(request)
    if engine is None or not engine.ready:
        return JSONResponse(
            status_code=503,
            content={"code": "model_not_ready", "message": "MADLAD is not ready"},
        )
    try:
        sha = engine.reload_adapter()
    except FileNotFoundError as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "adapter_missing", "message": str(exc)},
        )
    except Exception:
        logger.exception("MADLAD adapter reload failed")
        return JSONResponse(
            status_code=500,
            content={"code": "adapter_reload_failed", "message": "Reload failed"},
        )
    return ReloadAdapterResponse(
        reloaded=True,
        adapter_dir=request.app.state.settings.madlad_adapter_dir,
        adapter_sha256=sha,
    )
