"""Fundacao segura para recuperacao de senha por e-mail."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.auth.email_service import EmailSendResult, EmailService, mask_email
from src.auth.security import MIN_PASSWORD_LENGTH, hash_password
from src.auth.user_service import (
    AuthValidationError,
    _active_user_condition,
    _get_usuario_columns,
    _now,
    _normalize_email,
    get_auth_engine,
    safe_auth_exception_summary,
)
from src.auth.validation import EMAIL_RE

logger = logging.getLogger(__name__)

DEFAULT_PASSWORD_RESET_TOKEN_TTL_HOURS = 1
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8501"

PASSWORD_RESET_NEUTRAL_MESSAGE = "Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao."
PASSWORD_RESET_SUCCESS_MESSAGE = "Senha redefinida com sucesso. Voce ja pode entrar com a nova senha."
PASSWORD_RESET_INVALID_MESSAGE = "Link de recuperacao invalido ou expirado."
PASSWORD_RESET_USED_MESSAGE = "Este link de recuperacao ja foi utilizado."


def hash_password_reset_token(raw_token: str) -> str:
    """Gera hash irreversivel do token de recuperacao."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PasswordResetToken:
    user_id: int
    email: str
    raw_token: str
    expira_em: datetime


@dataclass(frozen=True)
class PasswordResetResult:
    success: bool
    status: str
    message: str
    user_id: int | None = None
    email: str | None = None
    send_result: EmailSendResult | None = None
    token_created: bool = False


def _safe_error_summary(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        return safe_auth_exception_summary(exc)
    return type(exc).__name__


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    text_value = str(value or "").strip()
    if not text_value:
        return datetime.min

    if text_value.endswith("Z"):
        text_value = f"{text_value[:-1]}+00:00"

    try:
        parsed = datetime.fromisoformat(text_value)
    except ValueError:
        return datetime.min

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed.replace(tzinfo=None)


def _log_audit_event(engine: Any, evento: str, **kwargs: Any) -> None:
    try:
        from src.audit.audit_log_service import log_audit_event_safely

        log_audit_event_safely(engine, evento, **kwargs)
    except Exception:
        logger.debug("audit_log nao disponivel ainda - ignorado em recuperacao_senha")


def _validate_reset_password(new_password: str, confirmation: str) -> str:
    if not new_password:
        raise AuthValidationError("Informe a nova senha.")
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise AuthValidationError(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
    if not confirmation or new_password != confirmation:
        raise AuthValidationError("As senhas nao coincidem.")
    return new_password


def _resolve_public_base_url(explicit_url: str | None = None) -> str:
    raw_url = (
        explicit_url
        or os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("EMAIL_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_URL")
        or DEFAULT_PUBLIC_BASE_URL
    ).strip()
    parsed = urlsplit(raw_url)
    if parsed.scheme and parsed.netloc:
        raw_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))
    return raw_url.rstrip("/")


class PasswordResetService:
    """Casos de uso para solicitacao e uso de token de recuperacao."""

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        app_public_url: str | None = None,
        initialize_schema: bool = True,
        token_ttl_hours: int = DEFAULT_PASSWORD_RESET_TOKEN_TTL_HOURS,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.app_public_url = _resolve_public_base_url(app_public_url)
        self.token_ttl_hours = token_ttl_hours
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "PasswordResetService":
        return cls(get_auth_engine(), email_service=EmailService.from_environment())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                {id_column},
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                criado_em TIMESTAMP NOT NULL,
                expira_em TIMESTAMP NOT NULL,
                usado_em TIMESTAMP NULL
            )
        """

        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_table_sql))
                conn.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS ux_password_reset_tokens_hash
                        ON password_reset_tokens (token_hash)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user
                        ON password_reset_tokens (user_id)
                        """
                    )
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=ensure_schema | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def create_password_reset_token(self, user_id: int) -> PasswordResetToken:
        try:
            with self.engine.begin() as conn:
                user = self._get_active_user_by_id(conn, user_id)
                if user is None:
                    raise AuthValidationError(PASSWORD_RESET_NEUTRAL_MESSAGE)

                raw_token = secrets.token_urlsafe(32)
                token_hash = hash_password_reset_token(raw_token)
                now = _now()
                expira_em = now + timedelta(hours=self.token_ttl_hours)
                conn.execute(
                    text(
                        """
                        INSERT INTO password_reset_tokens (
                            user_id,
                            token_hash,
                            criado_em,
                            expira_em
                        )
                        VALUES (
                            :user_id,
                            :token_hash,
                            :criado_em,
                            :expira_em
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "token_hash": token_hash,
                        "criado_em": now,
                        "expira_em": expira_em,
                    },
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=create_token | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        logger.info(
            "Token de recuperacao criado | user_id=%s | destinatario=%s",
            user_id,
            mask_email(user["email"]),
        )
        return PasswordResetToken(
            user_id=user_id,
            email=str(user["email"]),
            raw_token=raw_token,
            expira_em=expira_em,
        )

    def request_password_reset(self, email: str) -> PasswordResetResult:
        clean_email = _normalize_email(email)
        if not clean_email or not EMAIL_RE.match(clean_email):
            return PasswordResetResult(True, "neutral", PASSWORD_RESET_NEUTRAL_MESSAGE)

        try:
            with self.engine.connect() as conn:
                user = self._get_active_user_by_email(conn, clean_email)
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=find_user | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=password_reset_request",
                status="failure",
                source="auth",
                action="database",
            )
            return PasswordResetResult(False, "error", PASSWORD_RESET_NEUTRAL_MESSAGE)

        if user is None:
            logger.info("Recuperacao solicitada para e-mail sem conta ativa | destinatario=%s", mask_email(clean_email))
            return PasswordResetResult(True, "not_found", PASSWORD_RESET_NEUTRAL_MESSAGE)

        try:
            token = self.create_password_reset_token(int(user["id"]))
            reset_target = self._build_reset_target(token.raw_token)
            send_result = self.email_service.send_password_reset_email(
                token.email,
                reset_target,
                expires_in_minutes=self.token_ttl_hours * 60,
            )
        except Exception as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=request | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_id=int(user["id"]),
                user_email=clean_email,
                detalhe="message_type=password_reset; error_code=request_failed",
                status="failure",
                source="email",
                action="password_reset",
            )
            return PasswordResetResult(
                False,
                "send_failed",
                PASSWORD_RESET_NEUTRAL_MESSAGE,
                user_id=int(user["id"]),
                email=clean_email,
                token_created=False,
            )

        if send_result.mode == "fake" or (send_result.success and not send_result.sent):
            status = "fake"
        elif send_result.success and send_result.sent:
            status = "sent"
        else:
            status = "send_failed"

        logger.info(
            "Recuperacao de senha solicitada | user_id=%s | destinatario=%s | modo=%s | sucesso=%s",
            token.user_id,
            mask_email(token.email),
            send_result.mode,
            send_result.success,
        )
        _log_audit_event(
            self.engine,
            "password_reset_requested",
            user_id=token.user_id,
            user_email=token.email,
            detalhe=f"status={status}; mode={send_result.mode}; sent={bool(send_result.sent)}",
            status="info" if status != "send_failed" else "failure",
            source="auth",
            action="password_reset_request",
        )
        if status == "send_failed":
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_id=token.user_id,
                user_email=token.email,
                detalhe=f"message_type=password_reset; mode={send_result.mode}; error_code={send_result.error_code or 'send_failed'}",
                status="failure",
                source="email",
                action="password_reset",
            )
        return PasswordResetResult(
            send_result.success,
            status,
            PASSWORD_RESET_NEUTRAL_MESSAGE,
            user_id=token.user_id,
            email=token.email,
            send_result=send_result,
            token_created=True,
        )

    def validate_password_reset_token(self, raw_token: str) -> PasswordResetResult:
        clean_token = (raw_token or "").strip()
        if not clean_token:
            return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

        token_hash = hash_password_reset_token(clean_token)
        try:
            with self.engine.connect() as conn:
                row = self._get_token_row(conn, token_hash)
                return self._validate_token_row(conn, row)
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=validate | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def reset_password_with_token(
        self,
        raw_token: str,
        new_password: str,
        confirmation: str,
    ) -> PasswordResetResult:
        clean_password = _validate_reset_password(new_password, confirmation)
        clean_token = (raw_token or "").strip()
        if not clean_token:
            return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

        token_hash = hash_password_reset_token(clean_token)
        try:
            with self.engine.begin() as conn:
                row = self._get_token_row(conn, token_hash)
                validation = self._validate_token_row(conn, row)
                if not validation.success:
                    return validation

                now = _now()
                update_result = conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET senha_hash = :senha_hash,
                            atualizado_em = :atualizado_em
                        WHERE id = :user_id
                          AND {_active_user_condition(_get_usuario_columns(conn))}
                        """
                    ),
                    {
                        "user_id": validation.user_id,
                        "senha_hash": hash_password(clean_password),
                        "atualizado_em": now,
                    },
                )
                if update_result.rowcount == 0:
                    return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

                conn.execute(
                    text(
                        """
                        UPDATE password_reset_tokens
                        SET usado_em = :usado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "usado_em": now},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro recuperacao_senha | acao=reset | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                detalhe="operacao=password_reset_complete",
                status="failure",
                source="auth",
                action="database",
            )
            raise

        _log_audit_event(
            self.engine,
            "password_reset_completed",
            user_id=validation.user_id,
            user_email=validation.email,
            detalhe="resultado=senha_redefinida",
            status="success",
            source="auth",
            action="password_reset_complete",
        )
        return PasswordResetResult(
            True,
            "reset",
            PASSWORD_RESET_SUCCESS_MESSAGE,
            user_id=validation.user_id,
            email=validation.email,
        )

    def _get_active_user_by_id(self, conn: Any, user_id: int) -> Any | None:
        active_condition = _active_user_condition(_get_usuario_columns(conn))
        return conn.execute(
            text(
                f"""
                SELECT id, email
                FROM usuarios
                WHERE id = :id
                  AND {active_condition}
                LIMIT 1
                """
            ),
            {"id": user_id},
        ).mappings().first()

    def _get_active_user_by_email(self, conn: Any, email: str) -> Any | None:
        active_condition = _active_user_condition(_get_usuario_columns(conn))
        return conn.execute(
            text(
                f"""
                SELECT id, email
                FROM usuarios
                WHERE lower(email) = :email
                  AND {active_condition}
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()

    def _get_token_row(self, conn: Any, token_hash: str) -> Any | None:
        return conn.execute(
            text(
                """
                SELECT id, user_id, expira_em, usado_em
                FROM password_reset_tokens
                WHERE token_hash = :token_hash
                LIMIT 1
                """
            ),
            {"token_hash": token_hash},
        ).mappings().first()

    def _validate_token_row(self, conn: Any, row: Any | None) -> PasswordResetResult:
        if row is None:
            return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE)

        user_id = int(row["user_id"])
        user = self._get_active_user_by_id(conn, user_id)
        if user is None:
            return PasswordResetResult(False, "invalid", PASSWORD_RESET_INVALID_MESSAGE, user_id=user_id)

        if row["usado_em"] is not None:
            return PasswordResetResult(
                False,
                "used",
                PASSWORD_RESET_USED_MESSAGE,
                user_id=user_id,
                email=str(user["email"]),
            )

        if _coerce_datetime(row["expira_em"]) <= _now():
            return PasswordResetResult(
                False,
                "expired",
                PASSWORD_RESET_INVALID_MESSAGE,
                user_id=user_id,
                email=str(user["email"]),
            )

        return PasswordResetResult(True, "valid", "", user_id=user_id, email=str(user["email"]))

    def _build_reset_target(self, raw_token: str) -> str:
        if not self.app_public_url:
            return raw_token

        separator = "&" if "?" in self.app_public_url else "?"
        return f"{self.app_public_url}{separator}{urlencode({'reset_password_token': raw_token})}"
