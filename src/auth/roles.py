"""Definicoes de papeis (roles) para controle de acesso baseado em funcoes (RBAC)."""

from __future__ import annotations

from typing import Any

# Papeis disponiveis no sistema.
ROLE_USER = "user"
ROLE_SUPER_ADMIN = "super_admin"

VALID_ROLES = {ROLE_USER, ROLE_SUPER_ADMIN}

ROLE_DISPLAY_NAMES = {
    ROLE_USER: "Usuário Padrão",
    ROLE_SUPER_ADMIN: "Super Administrador",
}


def is_super_admin(user: dict[str, Any] | None) -> bool:
    """Retorna True se o usuario autenticado for um Super Administrador."""
    if not user:
        return False
    return user.get("role") == ROLE_SUPER_ADMIN


def can_view_audit_log(user: dict[str, Any] | None) -> bool:
    """Retorna True se o usuario pode ver o log de auditoria.

    Super Admins sempre podem. Usuarios comuns podem somente se tiverem
    permissao explicitamente concedida (campo can_view_audit = True).
    """
    if not user:
        return False
    if is_super_admin(user):
        return True
    return bool(user.get("can_view_audit", False))


def role_display_name(role: str) -> str:
    """Retorna o nome legivel do papel."""
    return ROLE_DISPLAY_NAMES.get(role, role)
