"""FastAPI application for the admin message lifecycle dashboard."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette import status
from starlette.middleware.sessions import SessionMiddleware

from telegram_agent.core.admin_dashboard.api.v1.auth import login_form, logout
from telegram_agent.core.admin_dashboard.api.v1.router import api_router
from telegram_agent.core.admin_dashboard.common.settings import settings
from telegram_agent.core.admin_dashboard.common.types import DbName
from telegram_agent.core.admin_dashboard.db.engines import DashboardDatabases
from telegram_agent.core.common.logging import setup_logging

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        databases = DashboardDatabases(settings)
        databases.start()
        app.state.databases = databases
        app.state.templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
        logger.info("Admin dashboard started")
        try:
            yield
        finally:
            await databases.dispose()
            logger.info("Admin dashboard stopped")

    setup_logging(settings.log_level)
    app = FastAPI(
        title="Telegram Agent Admin Dashboard",
        description="Read-only operational view of Telegram message lifecycles",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )

    secret = settings.session_secret or "insecure-dev-session-secret-change-me"
    if settings.session_secret is None:
        logger.warning("SESSION_SECRET is not set; using an insecure development default")

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie=settings.session_cookie_name,
        https_only=settings.session_https_only,
        same_site="lax",
    )

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.include_router(api_router)

    @app.get("/health")
    @app.get("/health/")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "admin-dashboard",
            "version": "0.1.0",
        }

    @app.get("/health/deps")
    async def health_deps(request: Request) -> dict[str, object]:
        databases: DashboardDatabases = request.app.state.databases
        deps: dict[str, str] = {}
        for name in DbName:
            try:
                await databases.ping(name)
                deps[name.value] = "ok"
            except Exception as exc:  # noqa: BLE001 - report all connection failures
                deps[name.value] = f"error: {exc.__class__.__name__}"
        return {"status": "ok", "databases": deps}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        templates: Jinja2Templates = request.app.state.templates
        error = request.query_params.get("error")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": bool(error)},
        )

    @app.post("/login")
    async def login_submit(request: Request) -> RedirectResponse:
        form = await request.form()
        return await login_form(
            request,
            username=str(form.get("username") or ""),
            password=str(form.get("password") or ""),
        )

    @app.post("/logout")
    async def logout_submit(request: Request) -> RedirectResponse:
        return await logout(request)

    @app.exception_handler(status.HTTP_303_SEE_OTHER)
    async def see_other_handler(request: Request, exc):  # type: ignore[no-untyped-def]
        # FastAPI HTTPException with 303 is unusual; require_admin raises HTTPException
        # with Location header — handle generically below.
        return RedirectResponse(
            url=exc.headers.get("Location", "/login") if exc.headers else "/login",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    from fastapi import HTTPException
    from fastapi.responses import Response

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
        if exc.status_code == status.HTTP_303_SEE_OTHER:
            location = (exc.headers or {}).get("Location", "/login")
            return RedirectResponse(url=location, status_code=status.HTTP_303_SEE_OTHER)
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        return HTMLResponse(
            content=f"<h1>{exc.status_code}</h1><p>{exc.detail}</p>",
            status_code=exc.status_code,
        )

    return app


fastapi_app = create_app()
