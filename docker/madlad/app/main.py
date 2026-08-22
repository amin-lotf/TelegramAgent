from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.engine import MadladEngine
from app.routes import router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = app.state.settings
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if settings.skip_model_load:
        logger.warning("SKIP_MODEL_LOAD=true; MADLAD model will not be loaded")
        app.state.engine = None
    else:
        engine = MadladEngine(
            model_id=settings.madlad_model_id,
            adapter_dir=settings.madlad_adapter_dir,
            device=settings.madlad_device,
            max_batch_size=settings.madlad_max_batch_size,
            default_beam_size=settings.madlad_beam_size,
            default_max_new_tokens=settings.madlad_max_new_tokens,
            max_source_length=settings.madlad_max_source_length,
            max_input_chars=settings.madlad_max_input_chars,
            gpu_concurrency=settings.madlad_gpu_concurrency,
            hf_token=os.environ.get("HF_TOKEN") or None,
        )
        engine.load()
        app.state.engine = engine
    yield
    app.state.engine = None


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(
        title="TelegramAgent MADLAD Translation Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.include_router(router)
    return app


app = create_app()
