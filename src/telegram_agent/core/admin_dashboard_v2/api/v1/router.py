from fastapi import APIRouter

from telegram_agent.core.admin_dashboard_v2.api.v1.routes.health import router as health_router
from telegram_agent.core.admin_dashboard_v2.api.v1.routes.messages import router as messages_router


router = APIRouter()
router.include_router(health_router)
router.include_router(messages_router)
