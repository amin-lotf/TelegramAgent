from fastapi import APIRouter

from telegram_agent.core.llm_gateway.api.v1.intent_classification.router import (
    router as intent_classification_router,
)
from telegram_agent.core.llm_gateway.api.v1.message_grouping.router import (
    router as message_grouping_router,
)

api_router = APIRouter()
api_router.include_router(message_grouping_router)
api_router.include_router(intent_classification_router)
