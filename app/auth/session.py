"""Session helpers — ported from src/auth/session.py, adapted to starlette request.session."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


def login_session(request: Request, user: dict[str, Any]) -> None:
    """Store only the public session payload: user_id, email, role, nome, can_view_audit."""
    request.session["user_id"] = user["id"]
    request.session["email"] = user["email"]
    request.session["role"] = user.get("role", "user")
    request.session["nome"] = user["nome"]
    request.session["can_view_audit"] = bool(user.get("can_view_audit", False))


def logout_session(request: Request) -> None:
    request.session.clear()


def get_authenticated_user(request: Request) -> dict[str, Any] | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None

    return {
        "id": user_id,
        "email": request.session.get("email"),
        "role": request.session.get("role", "user"),
        "nome": request.session.get("nome"),
        "can_view_audit": bool(request.session.get("can_view_audit", False)),
    }


def can_access_chat(request: Request) -> bool:
    return get_authenticated_user(request) is not None
