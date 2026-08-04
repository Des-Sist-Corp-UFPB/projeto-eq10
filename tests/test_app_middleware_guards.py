"""app/middleware/guards.py."""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import RedirectResponse

from app.middleware.guards import require_audit_access, require_authenticated, require_super_admin


def _request(path: str = "/protected", session: dict | None = None) -> Request:
    scope = {"type": "http", "path": path, "session": session if session is not None else {}, "headers": []}
    return Request(scope)


def _session_for(user: dict) -> dict:
    return {
        "user_id": user["id"],
        "email": user["email"],
        "role": user["role"],
        "nome": user["nome"],
        "can_view_audit": user["can_view_audit"],
    }


def test_require_authenticated_redirects_when_anonymous():
    result = require_authenticated(_request(path="/chat"))
    assert isinstance(result, RedirectResponse)
    assert result.status_code == 303
    assert "/auth/login?next=/chat" in result.headers["location"]


def test_require_authenticated_returns_user_when_logged_in(fake_user):
    result = require_authenticated(_request(session=_session_for(fake_user)))
    assert result == fake_user


def test_require_audit_access_redirects_when_anonymous():
    result = require_audit_access(_request(path="/auditoria"))
    assert isinstance(result, RedirectResponse)
    assert "/auth/login" in result.headers["location"]


def test_require_audit_access_redirects_when_no_permission(fake_user):
    result = require_audit_access(_request(session=_session_for(fake_user)))
    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "/estatisticas"


def test_require_audit_access_allows_admin(fake_admin):
    result = require_audit_access(_request(session=_session_for(fake_admin)))
    assert result == fake_admin


def test_require_audit_access_allows_flagged_user():
    user = {"id": 9, "email": "flag@example.com", "role": "user", "nome": "Flag", "can_view_audit": True}
    result = require_audit_access(_request(session=_session_for(user)))
    assert result == user


def test_require_super_admin_redirects_when_anonymous():
    result = require_super_admin(_request(path="/admin/users"))
    assert isinstance(result, RedirectResponse)
    assert "/auth/login" in result.headers["location"]


def test_require_super_admin_redirects_when_only_admin(fake_admin):
    result = require_super_admin(_request(session=_session_for(fake_admin)))
    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "/estatisticas"


def test_require_super_admin_allows_super_admin(fake_super_admin):
    result = require_super_admin(_request(session=_session_for(fake_super_admin)))
    assert result == fake_super_admin
