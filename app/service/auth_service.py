"""Authentication business logic — ported from src/auth/user_service.py (UserService)
and src/auth/validation.py. Owns validation, password hashing/verification,
transaction coordination and audit logging for the auth domain.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.auth.security import MIN_PASSWORD_LENGTH, hash_password, verify_password
from app.database import auth_db
from app.database.connection import get_auth_connection
from app.service import audit_service
from app.service.email_service import EmailService

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULT_PASSWORD_RESET_TOKEN_TTL_HOURS = 1
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8080"

PASSWORD_RESET_NEUTRAL_MESSAGE = "Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao."
PASSWORD_RESET_SUCCESS_MESSAGE = "Senha redefinida com sucesso. Voce ja pode entrar com a nova senha."
PASSWORD_RESET_INVALID_MESSAGE = "Link de recuperacao invalido ou expirado."
PASSWORD_RESET_USED_MESSAGE = "Este link de recuperacao ja foi utilizado."


class AuthValidationError(ValueError):
    """Erro seguro para exibicao na interface."""

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


def normalize_email(email: str) -> str:
    return (email or "").strip().casefold()


def _validate_name(nome: str) -> str:
    clean_name = (nome or "").strip()
    if not clean_name:
        raise AuthValidationError("Informe seu nome.")
    return clean_name


def _validate_email(email: str) -> str:
    clean_email = normalize_email(email)
    if not clean_email:
        raise AuthValidationError("Informe seu e-mail.")
    if not EMAIL_RE.match(clean_email):
        raise AuthValidationError("Informe um e-mail válido.")
    return clean_email


def _validate_new_password(password: str, confirmation: str | None = None) -> str:
    if not password:
        raise AuthValidationError("Informe uma senha.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthValidationError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if confirmation is not None and not confirmation:
        raise AuthValidationError("Confirme sua senha.")
    if confirmation is not None and password != confirmation:
        raise AuthValidationError("As senhas não coincidem.")
    return password


def register(nome: str, email: str, password: str, password_confirmation: str) -> dict[str, Any]:
    """Creates the account and returns it. Session login happens at the route layer."""
    clean_name = _validate_name(nome)
    clean_email = _validate_email(email)
    clean_password = _validate_new_password(password, password_confirmation)

    conn = get_auth_connection()
    try:
        if auth_db.active_email_exists(conn, clean_email):
            raise AuthValidationError("Já existe uma conta ativa com este e-mail.")

        user_id = auth_db.create_user(conn, clean_name, clean_email, hash_password(clean_password), "user")
        user = auth_db.get_user_by_id(conn, user_id)
    finally:
        conn.close()

    audit_service.log_event_safely(
        audit_service.EVENT_ACCOUNT_CREATED,
        user_id=user["id"],
        user_email=user["email"],
        detalhe=f"role={user['role']}; provider=password",
        status="success",
        source="auth",
        action="account_created",
    )
    return user


def authenticate(email: str, password: str) -> dict[str, Any]:
    clean_email = _validate_email(email)
    if not password:
        audit_service.log_event_safely(
            audit_service.EVENT_LOGIN_FAILURE,
            user_email=clean_email,
            detalhe="motivo=senha_ausente",
            status="failure",
            source="auth",
            action="login",
        )
        raise AuthValidationError("Informe sua senha.")

    conn = get_auth_connection()
    try:
        row = auth_db.get_user_by_email(conn, clean_email)
        if not row or not row["senha_hash"] or not verify_password(password, row["senha_hash"]):
            audit_service.log_event_safely(
                audit_service.EVENT_LOGIN_FAILURE,
                user_id=row["id"] if row else None,
                user_email=clean_email,
                detalhe="motivo=credenciais_invalidas",
                status="failure",
                source="auth",
                action="login",
            )
            raise AuthValidationError("E-mail ou senha inválidos.")

        auth_db.update_last_login(conn, row["id"])
        user = auth_db.get_user_by_id(conn, row["id"])
    finally:
        conn.close()

    audit_service.log_event_safely(
        audit_service.EVENT_LOGIN,
        user_id=user["id"],
        user_email=user["email"],
        detalhe="provider=password",
        status="success",
        source="auth",
        action="login",
    )
    return user


def logout(user: dict[str, Any] | None) -> None:
    """Logs the audit event. Clearing request.session is the route's job (app/auth/session.py)."""
    if not user:
        return
    audit_service.log_event_safely(
        audit_service.EVENT_LOGOUT,
        user_id=user.get("id"),
        user_email=user.get("email"),
        detalhe="logout_usuario",
        status="info",
        source="auth",
        action="logout",
    )


def update_profile_name(user_id: int, nome: str) -> dict[str, Any]:
    clean_name = _validate_name(nome)
    conn = get_auth_connection()
    try:
        auth_db.update_user_name(conn, user_id, clean_name)
        user = auth_db.get_user_by_id(conn, user_id)
    finally:
        conn.close()

    if user is None:
        raise AuthValidationError("Usuario ativo nao encontrado.")
    return user


def update_profile_email(user_id: int, email: str) -> dict[str, Any]:
    clean_email = _validate_email(email)
    conn = get_auth_connection()
    try:
        if auth_db.active_email_exists(conn, clean_email, exclude_user_id=user_id):
            raise AuthValidationError("Já existe uma conta ativa com este e-mail.")
        auth_db.update_user_email(conn, user_id, clean_email)
        user = auth_db.get_user_by_id(conn, user_id)
    finally:
        conn.close()

    if user is None:
        raise AuthValidationError("Usuario ativo nao encontrado.")
    return user


def change_password(user_id: int, senha_atual: str, nova_senha: str, confirmar_senha: str) -> None:
    clean_new_password = _validate_new_password(nova_senha, confirmar_senha)
    conn = get_auth_connection()
    try:
        current_hash = auth_db.get_password_hash(conn, user_id)
        if not current_hash or not verify_password(senha_atual, current_hash):
            raise AuthValidationError("Senha atual invalida.")
        auth_db.update_user_password(conn, user_id, hash_password(clean_new_password))
    finally:
        conn.close()


def deactivate_account(user: dict[str, Any]) -> None:
    conn = get_auth_connection()
    try:
        auth_db.deactivate_own_account(conn, user["id"])
    finally:
        conn.close()

    audit_service.log_event_safely(
        audit_service.EVENT_ACCOUNT_DELETED,
        user_id=user["id"],
        user_email=user["email"],
        status="success",
        source="auth",
        action="account_deactivated",
    )


# ── Password reset — ported from src/auth/password_reset_service.py ──────────────


@dataclass(frozen=True)
class PasswordResetResult:
    success: bool
    status: str
    message: str
    user_id: int | None = None
    email: str | None = None


def hash_password_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _now_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _resolve_public_base_url() -> str:
    raw_url = (
        os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("EMAIL_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_URL")
        or DEFAULT_PUBLIC_BASE_URL
    ).strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme and parsed.netloc:
        raw_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return raw_url.rstrip("/")


def _build_reset_target(raw_token: str) -> str:
    base_url = _resolve_public_base_url()
    reset_path = f"{base_url}/auth/reset-password"
    separator = "&" if "?" in reset_path else "?"
    return f"{reset_path}{separator}{urlencode({'reset_password_token': raw_token})}"


def request_password_reset(email: str) -> PasswordResetResult:
    """Always returns a neutral message — never reveals whether the email has an account."""
    clean_email = normalize_email(email)
    if not clean_email or not EMAIL_RE.match(clean_email):
        return PasswordResetResult(True, "neutral", PASSWORD_RESET_NEUTRAL_MESSAGE)

    conn = get_auth_connection()
    try:
        user = auth_db.get_user_by_email(conn, clean_email)
        if user is None:
            return PasswordResetResult(True, "not_found", PASSWORD_RESET_NEUTRAL_MESSAGE)

        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_password_reset_token(raw_token)
        now = _now_naive()
        expira_em = now + timedelta(hours=DEFAULT_PASSWORD_RESET_TOKEN_TTL_HOURS)
        auth_db.create_password_reset_token(conn, user["id"], token_hash, now, expira_em)
    finally:
        conn.close()

    reset_target = _build_reset_target(raw_token)
    send_result = EmailService.from_environment().send_password_reset_email(
        user["email"], reset_target, expires_in_minutes=DEFAULT_PASSWORD_RESET_TOKEN_TTL_HOURS * 60
    )

    if send_result.mode == "fake" or (send_result.success and not send_result.sent):
        status = "fake"
    elif send_result.success and send_result.sent:
        status = "sent"
    else:
        status = "send_failed"

    audit_service.log_event_safely(
        audit_service.EVENT_PASSWORD_RESET_REQUESTED,
        user_id=user["id"],
        user_email=user["email"],
        detalhe=f"status={status}; mode={send_result.mode}; sent={bool(send_result.sent)}",
        status="info" if status != "send_failed" else "failure",
        source="auth",
        action="password_reset_request",
    )
    if status == "send_failed":
        audit_service.log_event_safely(
            audit_service.EVENT_EMAIL_SENDING_FAILURE,
            user_id=user["id"],
            user_email=user["email"],
            detalhe=f"message_type=password_reset; mode={send_result.mode}; error_code={send_result.error_code or 'send_failed'}",
            status="failure",
            source="email",
            action="password_reset",
        )

    return PasswordResetResult(send_result.success, status, PASSWORD_RESET_NEUTRAL_MESSAGE, user["id"], user["email"])


def _validate_token_row(conn: Any, row: dict[str, Any] | None) -> PasswordResetResult:
    if row is None:
        return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

    user_id = int(row["user_id"])
    user = auth_db.get_user_by_id(conn, user_id)
    if user is None:
        return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE, user_id=user_id)

    if row["usado_em"] is not None:
        return PasswordResetResult(False, "used", PASSWORD_RESET_USED_MESSAGE, user_id, user["email"])

    expira_em = row["expira_em"]
    if expira_em.tzinfo is not None:
        expira_em = expira_em.astimezone(timezone.utc).replace(tzinfo=None)
    if expira_em <= _now_naive():
        return PasswordResetResult(False, "expired", PASSWORD_RESET_INVALID_MESSAGE, user_id, user["email"])

    return PasswordResetResult(True, "valid", "", user_id, user["email"])


def validate_reset_token(raw_token: str) -> PasswordResetResult:
    clean_token = (raw_token or "").strip()
    if not clean_token:
        return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

    conn = get_auth_connection()
    try:
        row = auth_db.get_password_reset_token_by_hash(conn, hash_password_reset_token(clean_token))
        return _validate_token_row(conn, row)
    finally:
        conn.close()


def reset_password_with_token(raw_token: str, new_password: str, confirmation: str) -> PasswordResetResult:
    if not new_password:
        raise AuthValidationError("Informe a nova senha.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise AuthValidationError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if not confirmation or new_password != confirmation:
        raise AuthValidationError("As senhas nao coincidem.")

    clean_token = (raw_token or "").strip()
    if not clean_token:
        return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

    conn = get_auth_connection()
    try:
        row = auth_db.get_password_reset_token_by_hash(conn, hash_password_reset_token(clean_token))
        validation = _validate_token_row(conn, row)
        if not validation.success:
            return validation

        rowcount = auth_db.update_active_user_password(conn, validation.user_id, hash_password(new_password))
        if rowcount == 0:
            return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

        auth_db.mark_password_reset_token_used(conn, row["id"], _now_naive())
    finally:
        conn.close()

    audit_service.log_event_safely(
        audit_service.EVENT_PASSWORD_RESET_COMPLETED,
        user_id=validation.user_id,
        user_email=validation.email,
        detalhe="resultado=senha_redefinida",
        status="success",
        source="auth",
        action="password_reset_complete",
    )
    return PasswordResetResult(True, "reset", PASSWORD_RESET_SUCCESS_MESSAGE, validation.user_id, validation.email)
