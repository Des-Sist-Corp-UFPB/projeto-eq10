"""Route-level auth guards. Routes call these and redirect when a RedirectResponse is returned."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.auth.roles import can_view_audit_log, is_super_admin
from app.auth.session import get_authenticated_user


def require_authenticated(request: Request) -> dict[str, Any] | RedirectResponse:
    user = get_authenticated_user(request)
    if user is None:
        return RedirectResponse(url=f"/auth/login?next={request.url.path}", status_code=303)
    return user


def require_audit_access(request: Request) -> dict[str, Any] | RedirectResponse:
    user = get_authenticated_user(request)
    if user is None:
        return RedirectResponse(url=f"/auth/login?next={request.url.path}", status_code=303)
    if not can_view_audit_log(user):
        return RedirectResponse(url="/estatisticas", status_code=303)
    return user


def require_super_admin(request: Request) -> dict[str, Any] | RedirectResponse:
    user = get_authenticated_user(request)
    if user is None:
        return RedirectResponse(url=f"/auth/login?next={request.url.path}", status_code=303)
    if not is_super_admin(user):
        return RedirectResponse(url="/estatisticas", status_code=303)
    return user
