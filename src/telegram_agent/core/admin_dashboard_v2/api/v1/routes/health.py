from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from telegram_agent.core.admin_dashboard_v2.security.authentication import require_admin


router = APIRouter(tags=["health"])


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok", "service": "admin-dashboard-v2"}


@router.get("/health/dependencies")
async def dependency_health(
    request: Request,
    _: Annotated[str, Depends(require_admin)],
) -> dict[str, object]:
    states = await request.app.state.read_databases.dependency_states()
    return {
        "status": "ok",
        "service": "admin-dashboard-v2",
        "dependencies": [
            {
                "source": state.source,
                "status": state.status.value,
                "message": state.message,
            }
            for state in states
        ],
    }
