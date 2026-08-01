"""User management business logic (super_admin only) — ported from
src/auth/user_service.py:UserService.get_all_users/set_role/set_audit_access/soft_delete_user.
"""

from __future__ import annotations

from typing import Any

from app.auth.roles import VALID_ROLES
from app.database import auth_db, users_db
from app.database.connection import get_auth_connection
from app.service import audit_service
from app.service.auth_service import AuthValidationError


def get_all_users() -> list[dict[str, Any]]:
    conn = get_auth_connection()
    try:
        return users_db.get_all_users(conn)
    finally:
        conn.close()


def set_role(user_id: int, new_role: str, acting_admin_id: int, acting_admin_email: str) -> dict[str, Any]:
    if new_role not in VALID_ROLES:
        raise AuthValidationError(f"Papel invalido: {new_role}")

    conn = get_auth_connection()
    try:
        users_db.update_user_role(conn, user_id, new_role)
        user = auth_db.get_user_by_id(conn, user_id)
    finally:
        conn.close()

    if user is None:
        raise AuthValidationError("Usuario ativo nao encontrado.")

    audit_service.log_event_safely(
        audit_service.EVENT_ROLE_CHANGED,
        user_id=user_id,
        user_email=user["email"],
        detalhe=f"novo_role={new_role} | admin_id={acting_admin_id} | admin={acting_admin_email}",
        status="info",
        source="admin",
        action="role_changed",
    )
    return user


def set_audit_access(user_id: int, grant: bool, acting_admin_id: int, acting_admin_email: str) -> None:
    conn = get_auth_connection()
    try:
        users_db.update_audit_access(conn, user_id, grant)
    finally:
        conn.close()

    evento = audit_service.EVENT_ACCESS_GRANTED if grant else audit_service.EVENT_ACCESS_REVOKED
    audit_service.log_event_safely(
        evento,
        user_id=user_id,
        detalhe=f"admin_id={acting_admin_id} | admin={acting_admin_email}",
        status="success" if grant else "info",
        source="admin",
        action="audit_access",
    )


def soft_delete_user(user_id: int) -> None:
    conn = get_auth_connection()
    try:
        user = auth_db.get_user_by_id(conn, user_id)
        users_db.soft_delete_user(conn, user_id)
    finally:
        conn.close()

    audit_service.log_event_safely(
        audit_service.EVENT_ACCOUNT_DELETED,
        user_id=user_id,
        user_email=user["email"] if user else None,
        status="success",
        source="auth",
        action="account_deactivated",
    )
