from __future__ import annotations

import hmac
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from telegram_agent.core.admin_dashboard_v2.common.settings import Settings
from telegram_agent.core.admin_dashboard_v2.security.passwords import verify_password


logger = logging.getLogger(__name__)
http_basic = HTTPBasic(auto_error=False)


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(http_basic)],
) -> str:
    settings: Settings = request.app.state.dashboard_settings
    authenticated = False
    supplied_username = "-"
    if credentials is not None:
        supplied_username = credentials.username
        username_matches = hmac.compare_digest(
            credentials.username.encode("utf-8"),
            settings.admin_username.encode("utf-8"),
        )
        password_matches = verify_password(
            credentials.password,
            settings.admin_password_hash.get_secret_value(),
        )
        authenticated = username_matches and password_matches

    if not authenticated:
        logger.warning(
            "Dashboard authentication failed",
            extra={"admin_username": supplied_username},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Administrator authentication required",
            headers={"WWW-Authenticate": f'Basic realm="{settings.auth_realm}"'},
        )
    return settings.admin_username
