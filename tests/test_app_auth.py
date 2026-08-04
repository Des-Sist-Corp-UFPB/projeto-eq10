"""app/auth/session.py + app/auth/roles.py."""

from __future__ import annotations

from starlette.requests import Request

from app.auth.roles import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN,
    ROLE_USER,
    can_view_audit_log,
    is_admin,
    is_super_admin,
    role_display_name,
)
from app.auth.session import can_access_chat, get_authenticated_user, login_session, logout_session


def _request(path: str = "/", session: dict | None = None) -> Request:
    scope = {"type": "http", "path": path, "session": session if session is not None else {}, "headers": []}
    return Request(scope)


# ── session.py ──────────────────────────────────────────────────────────────────


def test_login_session_stores_only_public_fields():
    request = _request()
    login_session(request, {"id": 1, "email": "ana@example.com", "role": "admin", "nome": "Ana", "can_view_audit": True, "senha_hash": "should-not-leak"})

    assert request.session == {
        "user_id": 1,
        "email": "ana@example.com",
        "role": "admin",
        "nome": "Ana",
        "can_view_audit": True,
    }


def test_login_session_defaults_role_and_audit_flag():
    request = _request()
    login_session(request, {"id": 2, "email": "b@example.com", "nome": "B"})

    assert request.session["role"] == "user"
    assert request.session["can_view_audit"] is False


def test_logout_session_clears_everything():
    request = _request(session={"user_id": 1, "email": "a@b.com", "role": "user", "nome": "A", "can_view_audit": False})
    logout_session(request)
    assert request.session == {}


def test_get_authenticated_user_returns_none_when_absent():
    assert get_authenticated_user(_request()) is None


def test_get_authenticated_user_returns_none_when_user_id_falsy():
    assert get_authenticated_user(_request(session={"user_id": 0})) is None


def test_get_authenticated_user_returns_dict_when_present():
    request = _request(session={"user_id": 5, "email": "x@y.com", "role": "super_admin", "nome": "X", "can_view_audit": True})
    user = get_authenticated_user(request)
    assert user == {"id": 5, "email": "x@y.com", "role": "super_admin", "nome": "X", "can_view_audit": True}


def test_can_access_chat_true_only_when_authenticated():
    assert can_access_chat(_request()) is False
    assert can_access_chat(_request(session={"user_id": 1})) is True


# ── roles.py ────────────────────────────────────────────────────────────────────


def test_is_super_admin():
    assert is_super_admin({"role": ROLE_SUPER_ADMIN}) is True
    assert is_super_admin({"role": ROLE_ADMIN}) is False
    assert is_super_admin(None) is False
    assert is_super_admin({}) is False


def test_is_admin_includes_super_admin():
    assert is_admin({"role": ROLE_ADMIN}) is True
    assert is_admin({"role": ROLE_SUPER_ADMIN}) is True
    assert is_admin({"role": ROLE_USER}) is False
    assert is_admin(None) is False


def test_can_view_audit_log():
    assert can_view_audit_log(None) is False
    assert can_view_audit_log({"role": ROLE_ADMIN, "can_view_audit": False}) is True
    assert can_view_audit_log({"role": ROLE_SUPER_ADMIN, "can_view_audit": False}) is True
    assert can_view_audit_log({"role": ROLE_USER, "can_view_audit": True}) is True
    assert can_view_audit_log({"role": ROLE_USER, "can_view_audit": False}) is False


def test_role_display_name_known_and_unknown():
    assert role_display_name(ROLE_USER) == "Usuário Padrão"
    assert role_display_name(ROLE_ADMIN) == "Administrador"
    assert role_display_name(ROLE_SUPER_ADMIN) == "Super Administrador"
    assert role_display_name("bogus") == "bogus"
