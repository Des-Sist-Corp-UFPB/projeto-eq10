"""RBAC role definitions — ported from src/auth/roles.py."""

from __future__ import annotations

from typing import Any

ROLE_USER = "user"
ROLE_ADMIN = "admin"
ROLE_SUPER_ADMIN = "super_admin"

VALID_ROLES = {ROLE_USER, ROLE_ADMIN, ROLE_SUPER_ADMIN}

ROLE_DISPLAY_NAMES = {
    ROLE_USER: "Usuário Padrão",
    ROLE_ADMIN: "Administrador",
    ROLE_SUPER_ADMIN: "Super Administrador",
}


def is_super_admin(user: dict[str, Any] | None) -> bool:
    """Retorna True se o usuario autenticado for um Super Administrador."""
    return bool(user) and user.get("role") == ROLE_SUPER_ADMIN


def is_admin(user: dict[str, Any] | None) -> bool:
    """Retorna True se o usuario autenticado for Administrador ou Super Admin."""
    return bool(user) and user.get("role") in {ROLE_ADMIN, ROLE_SUPER_ADMIN}


def can_view_audit_log(user: dict[str, Any] | None) -> bool:
    """Retorna True se o usuario pode ver o log de auditoria."""
    if not user:
        return False
    if is_admin(user):
        return True
    return bool(user.get("can_view_audit", False))


def role_display_name(role: str) -> str:
    """Retorna o nome legivel do papel."""
    return ROLE_DISPLAY_NAMES.get(role, role)
