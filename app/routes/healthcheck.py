"""GET /healthcheck — JSON heartbeat for Uptime Kuma. No session required. Checks both
auth and analytics databases via the untouched src/diagnostics/health_service.py.

GET /health — readiness probe matching the legacy contract in docs/READINESS.md: HTTP 200
when the auth DB answers SELECT 1, HTTP 503 otherwise. Deliberately does NOT touch the
analytics DB, OTel, or Umami — per READINESS.md, none of those affect this result. This is
NOT what Dockerfile.fastapi's own HEALTHCHECK polls (that stays on /healthcheck, which
always returns 200) — READINESS.md is explicit that Docker's liveness probe should stay on
the always-a-response endpoint, and readiness (this one) should be monitored externally,
precisely so a transient DB blip doesn't get the container killed for being "unhealthy"
when the process itself is fine.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database.connection import get_auth_connection

router = APIRouter()


@router.get("/healthcheck")
def get_healthcheck() -> JSONResponse:
    try:
        from src.diagnostics.health_service import HealthService

        result = HealthService().run_heartbeat()
        payload = result.as_dict()
    except Exception as exc:
        payload = {
            "name": "heartbeat",
            "status": "error",
            "message": f"Heartbeat abortou com excecao inesperada: {type(exc).__name__}",
            "details": {},
        }

    return JSONResponse(payload, status_code=200)


@router.get("/health")
def get_health() -> JSONResponse:
    """Readiness probe: HTTP 200 if the auth DB is reachable, 503 otherwise.
    Never leaks credentials, SQL, host, or exception details — matches docs/READINESS.md.
    """
    try:
        conn = get_auth_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        finally:
            conn.close()
        return JSONResponse(
            {"status": "healthy", "database": "connected"},
            status_code=200,
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        return JSONResponse(
            {"status": "unhealthy", "database": "unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
