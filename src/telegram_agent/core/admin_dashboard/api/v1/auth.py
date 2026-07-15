"""Session-based admin authentication for the HTML dashboard."""
from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse

from telegram_agent.core.admin_dashboard.common.settings import Settings, settings


def is_authenticated(request: Request) -> bool:
    user = request.session.get("admin_user")
    return bool(user)


def require_admin(request: Request) -> str:
    user = request.session.get("admin_user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return str(user)


def attempt_login(
    *,
    username: str,
    password: str,
    app_settings: Settings = settings,
) -> bool:
    if not app_settings.admin_password or not app_settings.session_secret:
        return False
    user_ok = secrets.compare_digest(username, app_settings.admin_username)
    pass_ok = secrets.compare_digest(password, app_settings.admin_password)
    return user_ok and pass_ok


async def login_form(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> RedirectResponse:
    if attempt_login(username=username, password=password):
        request.session["admin_user"] = username
        return RedirectResponse(url="/messages", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(url="/login?error=1", status_code=status.HTTP_303_SEE_OTHER)


async def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)


AdminUser = Annotated[str, Depends(require_admin)]
