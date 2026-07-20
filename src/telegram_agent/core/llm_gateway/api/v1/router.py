from fastapi import APIRouter

from telegram_agent.core.llm_gateway.api.v1.download_agent.router import (
    router as download_agent_router,
)
from telegram_agent.core.llm_gateway.api.v1.glossary_extraction.router import (
    router as glossary_extraction_router,
)
from telegram_agent.core.llm_gateway.api.v1.intent_classification.router import (
    router as intent_classification_router,
)
from telegram_agent.core.llm_gateway.api.v1.message_grouping.router import (
    router as message_grouping_router,
)
from telegram_agent.core.llm_gateway.api.v1.subtitle_translation.router import (
    router as subtitle_translation_router,
)

api_router = APIRouter()
api_router.include_router(message_grouping_router)
api_router.include_router(intent_classification_router)
api_router.include_router(download_agent_router)
api_router.include_router(glossary_extraction_router)
api_router.include_router(subtitle_translation_router)
