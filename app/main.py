"""FastAPI app factory: middleware setup, static files, templates, router includes."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.auth.roles import can_view_audit_log, is_super_admin
from app.auth.session import get_authenticated_user
from app.config.settings import get_settings
from app.database.schema_check import run_startup_checks
from app.routes import audit, auth, chat, estatisticas, healthcheck, users
from src.observability.telemetry import configure_telemetry
from src.observability.telemetry import span as otel_span

# uvicorn only attaches handlers to its own loggers ("uvicorn", "uvicorn.error",
# "uvicorn.access") — without this, every logger.info()/warning() call anywhere under
# app/ is silently dropped by the root logger's last-resort WARNING-only handler.
# Discovered while adding the startup schema-check log line below; not something
# --log-level on the uvicorn CLI fixes, since that flag only touches uvicorn's own loggers.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # configure_telemetry() takes no arguments — it reads OTEL_ENABLED, OTEL_SERVICE_NAME,
    # OTEL_EXPORTER_OTLP_* directly from the environment itself (see
    # src/observability/telemetry.py). It's idempotent/lock-guarded, logs the
    # "OpenTelemetry status | ..." line exactly once per process either way, and — when
    # successfully configured — auto-emits its own "app.startup" span internally via
    # _emit_startup_span_once(). That internal span hardcodes app.framework="streamlit"
    # (legacy code we don't touch), so the explicit span below duplicates it with the
    # correct framework label. Both are harmless/safe-attributes-only; documented in
    # docs/claude-migration.md rather than silently worked around.
    configure_telemetry()
    run_startup_checks()
    settings = get_settings()
    with otel_span(
        "app.startup",
        {
            "app.framework": "fastapi",
            "deployment.environment": settings.environment,
            "telemetry.verification": "startup",
        },
    ):
        pass
    yield


def _build_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
    templates.env.globals["get_authenticated_user"] = get_authenticated_user
    templates.env.globals["can_view_audit_log"] = can_view_audit_log
    templates.env.globals["is_super_admin"] = is_super_admin
    return templates


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(title="Secretaria de Saúde — Mamanguape", lifespan=_lifespan)

    https_only = settings.environment == "production"
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        session_cookie="session",
        same_site="lax",
        https_only=https_only,
    )
    logger.info(
        "SessionMiddleware https_only=%s | Secure cookie flag is static, not per-request: "
        "if https_only=True, cookies are marked Secure unconditionally and will NOT be sent "
        "back over plain HTTP by any real browser or curl's cookie jar. Only set "
        "ENVIRONMENT=production once the browser-facing connection is actually HTTPS end to "
        "end (Starlette's SessionMiddleware does not consult X-Forwarded-Proto for this flag).",
        https_only,
    )

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    templates = _build_templates()
    templates.env.globals["logo_url"] = settings.logo_url
    templates.env.globals["email_verification_required"] = settings.email_verification_required
    # settings.umami_enabled already folds in "script_url and website_id both validated"
    # (see app/config/settings.py:get_settings()); this extra bool() is redundant but kept
    # for parity with the requested template-global contract.
    templates.env.globals["umami_enabled"] = (
        settings.umami_enabled and bool(settings.umami_script_url) and bool(settings.umami_website_id)
    )
    templates.env.globals["umami_script_url"] = settings.umami_script_url
    templates.env.globals["umami_website_id"] = settings.umami_website_id
    templates.env.globals["umami_host_url"] = settings.umami_host_url
    templates.env.globals["umami_allowed_domain"] = settings.umami_allowed_domain
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
