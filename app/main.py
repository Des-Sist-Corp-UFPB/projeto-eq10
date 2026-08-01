"""FastAPI app factory: middleware setup, static files, templates, router includes."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth.roles import can_view_audit_log, is_super_admin
from app.auth.session import get_authenticated_user
from app.config.settings import get_settings
from app.routes import audit, auth, chat, estatisticas, healthcheck, users

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


def _build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.globals["get_authenticated_user"] = get_authenticated_user
    templates.env.globals["can_view_audit_log"] = can_view_audit_log
    templates.env.globals["is_super_admin"] = is_super_admin
    return templates


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Secretaria de Saúde — Mamanguape")

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        session_cookie="session",
        same_site="lax",
        https_only=settings.environment == "production",
    )

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    templates = _build_templates()
    templates.env.globals["logo_url"] = settings.logo_url
    templates.env.globals["email_verification_required"] = settings.email_verification_required
    app.state.templates = templates
    app.state.settings = settings

    app.include_router(estatisticas.router)
    app.include_router(auth.router)
    app.include_router(chat.router)
    app.include_router(audit.router)
    app.include_router(users.router)
    app.include_router(healthcheck.router)

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/estatisticas", status_code=303)

    logger.info(
        "FastAPI app iniciado | environment=%s email_verification_required=%s otel_enabled=%s",
        settings.environment,
        settings.email_verification_required,
        settings.otel_enabled,
    )

    return app


app = create_app()
