"""GET /healthcheck — JSON heartbeat for Uptime Kuma. No session required. Checks both
auth and analytics databases via the untouched src/diagnostics/health_service.py.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

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
