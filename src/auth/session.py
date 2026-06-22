"""Helpers pequenos para controlar a sessao autenticada."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

AUTH_SESSION_KEY = "auth_user"


def public_user_payload(user: Any) -> dict[str, Any]:
    """Mantem na sessao apenas dados publicos do usuario."""
    if isinstance(user, dict):
        return {
            "id": user["id"],
            "nome": user["nome"],
            "email": user["email"],
            "role": user.get("role", "user"),
        }

    return {
        "id": user.id,
        "nome": user.nome,
        "email": user.email,
        "role": user.role,
    }


def login_session(session_state: MutableMapping[str, Any], user: Any) -> None:
    payload = public_user_payload(user)
    session_state[AUTH_SESSION_KEY] = payload
    session_state["auth_user_id"] = payload["id"]
    session_state["auth_user_name"] = payload["nome"]
    session_state["auth_user_email"] = payload["email"]
    session_state["is_authenticated"] = True


def logout_session(session_state: MutableMapping[str, Any]) -> None:
    session_state.pop(AUTH_SESSION_KEY, None)
    session_state.pop("auth_user_id", None)
    session_state.pop("auth_user_name", None)
    session_state.pop("auth_user_email", None)
    session_state["is_authenticated"] = False
    session_state.pop("pending_prompt", None)
    session_state.pop("chat_history_session_id", None)
    session_state["messages"] = []


def get_authenticated_user(session_state: MutableMapping[str, Any]) -> dict[str, Any] | None:
    user = session_state.get(AUTH_SESSION_KEY)
    if not isinstance(user, dict) or not user.get("id"):
        return None

    return user


def can_access_chat(session_state: MutableMapping[str, Any]) -> bool:
    return get_authenticated_user(session_state) is not None
