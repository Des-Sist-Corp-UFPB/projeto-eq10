"""Validacoes de formulario para autenticacao."""

from __future__ import annotations

import re

from src.auth.security import MIN_PASSWORD_LENGTH

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean_email(email: str) -> str:
    return (email or "").strip().casefold()


def validate_login_fields(email: str, password: str) -> dict[str, str]:
    errors: dict[str, str] = {}
    clean_email = _clean_email(email)

    if not clean_email:
        errors["email"] = "Informe seu e-mail."
    elif not EMAIL_RE.match(clean_email):
        errors["email"] = "Informe um e-mail válido."

    if not password:
        errors["senha"] = "Informe sua senha."

    return errors


def validate_register_fields(
    name: str,
    email: str,
    password: str,
    password_confirmation: str,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    clean_name = (name or "").strip()
    clean_email = _clean_email(email)

    if not clean_name:
        errors["nome"] = "Informe seu nome."

    if not clean_email:
        errors["email"] = "Informe seu e-mail."
    elif not EMAIL_RE.match(clean_email):
        errors["email"] = "Informe um e-mail válido."

    if not password:
        errors["senha"] = "Informe uma senha."
    elif len(password) < MIN_PASSWORD_LENGTH:
        errors["senha"] = f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres."

    if not password_confirmation:
        errors["confirmar_senha"] = "Confirme sua senha."
    elif password and password != password_confirmation:
        errors["confirmar_senha"] = "As senhas não coincidem."

    return errors
