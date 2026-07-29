"""Fundacao segura para verificacao de e-mail de usuarios."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.auth.email_service import EmailSendResult, EmailService, mask_email
from src.observability.telemetry import traced_operation
from src.auth.user_service import (
    AuthValidationError,
    _active_user_condition,
    _add_usuario_column_if_missing,
    _get_usuario_columns,
    _now,
    get_auth_engine,
    safe_auth_exception_summary,
)

logger = logging.getLogger(__name__)

EMAIL_VERIFICATION_REQUIRED_ENV = "EMAIL_VERIFICATION_REQUIRED"
DEFAULT_VERIFICATION_TOKEN_TTL_HOURS = 24
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8501"

EMAIL_VERIFICATION_FAKE_MESSAGE = (
    "Conta criada. A verificacao de e-mail sera enviada quando o servico de e-mail estiver configurado."
)
EMAIL_VERIFICATION_SENT_MESSAGE = "Conta criada. Enviamos um link de verificacao para seu e-mail."
EMAIL_VERIFICATION_SEND_FAILED_MESSAGE = "Conta criada, mas nao foi possivel enviar a verificacao agora."
EMAIL_VERIFICATION_RESEND_FAKE_MESSAGE = (
    "A verificacao de e-mail sera enviada quando o servico de e-mail estiver configurado."
)
EMAIL_VERIFICATION_RESEND_SENT_MESSAGE = "Enviamos um novo link de verificacao para seu e-mail."
EMAIL_VERIFICATION_RESEND_FAILED_MESSAGE = "Nao foi possivel enviar a verificacao agora."
EMAIL_VERIFICATION_SUCCESS_MESSAGE = "E-mail verificado com sucesso."
EMAIL_VERIFICATION_INVALID_MESSAGE = "Link de verificacao invalido ou expirado."
EMAIL_VERIFICATION_USED_MESSAGE = "Este link de verificacao ja foi utilizado."


def is_email_verification_required() -> bool:
    """Retorna se o acesso deve exigir e-mail verificado.

    O padrao e falso para nao bloquear usuarios enquanto o envio real ainda nao
    esta configurado.
    """
    raw_value = os.getenv(EMAIL_VERIFICATION_REQUIRED_ENV)
    if raw_value is None:
        return False

    return raw_value.strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def hash_email_verification_token(raw_token: str) -> str:
    """Gera hash irreversivel do token de verificacao."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmailVerificationToken:
    user_id: int
    email: str
    raw_token: str
    expira_em: datetime


@dataclass(frozen=True)
class EmailVerificationResult:
    success: bool
    status: str
    message: str
    user_id: int | None = None
    email: str | None = None
    send_result: EmailSendResult | None = None


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
        logger.debug("audit_log nao disponivel ainda - ignorado em verificacao_email")


def _resolve_public_base_url(explicit_url: str | None = None) -> str:
    return (
        explicit_url
        or os.getenv("EMAIL_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_URL")
        or DEFAULT_PUBLIC_BASE_URL
    ).strip().rstrip("/")


class EmailVerificationService:
    """Casos de uso para verificacao de e-mail.

    O servico cria tokens, armazena apenas o hash e usa EmailService para a
    entrega. O envio real permanece desativado por padrao.
    """

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        app_public_url: str | None = None,
        initialize_schema: bool = True,
        token_ttl_hours: int = DEFAULT_VERIFICATION_TOKEN_TTL_HOURS,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.app_public_url = _resolve_public_base_url(app_public_url)
        self.token_ttl_hours = token_ttl_hours
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "EmailVerificationService":
        return cls(get_auth_engine(), email_service=EmailService.from_environment())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS email_verification_tokens (
                {id_column},
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
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
                        CREATE UNIQUE INDEX IF NOT EXISTS ux_email_verification_tokens_hash
                        ON email_verification_tokens (token_hash)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_email_verification_tokens_user
                        ON email_verification_tokens (user_id)
                        """
                    )
                )
                columns = _get_usuario_columns(conn)
                _add_usuario_column_if_missing(
                    conn,
                    columns,
                    "email_verificado",
                    "BOOLEAN NOT NULL DEFAULT false",
                )
                _add_usuario_column_if_missing(conn, columns, "email_verificado_em", "TIMESTAMP NULL")
                conn.execute(
                    text("UPDATE usuarios SET email_verificado = false WHERE email_verificado IS NULL")
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=ensure_schema | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def create_email_verification_token(self, user_id: int, email: str | None = None) -> EmailVerificationToken:
        try:
            with self.engine.begin() as conn:
                clean_email = (email or self._get_active_user_email(conn, user_id)).strip().casefold()
                if not clean_email:
                    raise AuthValidationError("Usuario ativo nao encontrado.")

                raw_token = secrets.token_urlsafe(32)
                token_hash = hash_email_verification_token(raw_token)
                now = _now()
                expira_em = now + timedelta(hours=self.token_ttl_hours)
                conn.execute(
                    text(
                        """
                        INSERT INTO email_verification_tokens (
                            user_id,
                            email,
                            token_hash,
                            criado_em,
                            expira_em
                        )
                        VALUES (
                            :user_id,
                            :email,
                            :token_hash,
                            :criado_em,
                            :expira_em
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "email": clean_email,
                        "token_hash": token_hash,
                        "criado_em": now,
                        "expira_em": expira_em,
                    },
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=create_token | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        logger.info(
            "Token de verificacao criado | user_id=%s | destinatario=%s",
            user_id,
            mask_email(clean_email),
        )
        return EmailVerificationToken(
            user_id=user_id,
            email=clean_email,
            raw_token=raw_token,
            expira_em=expira_em,
        )

    @traced_operation("auth.email_verification_request", {"auth.operation": "email_verification_request", "auth.provider": "email"})
    def send_verification_email(self, user_id: int) -> EmailVerificationResult:
        try:
            token = self.create_email_verification_token(user_id)
            verification_target = self._build_verification_target(token.raw_token)
            send_result = self.email_service.send_verification_email(token.email, verification_target)
        except AuthValidationError as exc:
            return EmailVerificationResult(
                success=False,
                status="invalid_user",
                message=exc.public_message,
                user_id=user_id,
            )
        except Exception as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=send | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_id=user_id,
                detalhe="message_type=email_verification; error_code=send_failed",
                status="failure",
                source="email",
                action="email_verification",
            )
            return EmailVerificationResult(
                success=False,
                status="send_failed",
                message=EMAIL_VERIFICATION_SEND_FAILED_MESSAGE,
                user_id=user_id,
            )

        if send_result.mode == "fake" or (send_result.success and not send_result.sent):
            message = EMAIL_VERIFICATION_FAKE_MESSAGE
            status = "fake"
        elif send_result.success and send_result.sent:
            message = EMAIL_VERIFICATION_SENT_MESSAGE
            status = "sent"
        else:
            message = EMAIL_VERIFICATION_SEND_FAILED_MESSAGE
            status = "send_failed"
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_id=token.user_id,
                user_email=token.email,
                detalhe=f"message_type=email_verification; mode={send_result.mode}; error_code={send_result.error_code or 'send_failed'}",
                status="failure",
                source="email",
                action="email_verification",
            )

        logger.info(
            "Verificacao de e-mail solicitada | user_id=%s | destinatario=%s | modo=%s | sucesso=%s",
            token.user_id,
            mask_email(token.email),
            send_result.mode,
            send_result.success,
        )
        return EmailVerificationResult(
            success=send_result.success,
            status=status,
            message=message,
            user_id=token.user_id,
            email=token.email,
            send_result=send_result,
        )

    def resend_verification_email(self, user_id: int) -> EmailVerificationResult:
        result = self.send_verification_email(user_id)
        if result.status == "fake":
            return EmailVerificationResult(
                success=result.success,
                status=result.status,
                message=EMAIL_VERIFICATION_RESEND_FAKE_MESSAGE,
                user_id=result.user_id,
                email=result.email,
                send_result=result.send_result,
            )
        if result.status == "sent":
            return EmailVerificationResult(
                success=result.success,
                status=result.status,
                message=EMAIL_VERIFICATION_RESEND_SENT_MESSAGE,
                user_id=result.user_id,
                email=result.email,
                send_result=result.send_result,
            )
        if result.status == "send_failed":
            return EmailVerificationResult(
                success=False,
                status=result.status,
                message=EMAIL_VERIFICATION_RESEND_FAILED_MESSAGE,
                user_id=result.user_id,
                email=result.email,
                send_result=result.send_result,
            )
        return result

    @traced_operation("auth.email_verification", {"auth.operation": "email_verification", "auth.provider": "email"})
    def verify_email_token(self, raw_token: str) -> EmailVerificationResult:
        clean_token = (raw_token or "").strip()
        if not clean_token:
            return EmailVerificationResult(False, "invalid", EMAIL_VERIFICATION_INVALID_MESSAGE)

        token_hash = hash_email_verification_token(clean_token)
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT id, user_id, email, expira_em, usado_em
                        FROM email_verification_tokens
                        WHERE token_hash = :token_hash
                        LIMIT 1
                        """
                    ),
                    {"token_hash": token_hash},
                ).mappings().first()

                if row is None:
                    return EmailVerificationResult(False, "invalid", EMAIL_VERIFICATION_INVALID_MESSAGE)

                if row["usado_em"] is not None:
                    return EmailVerificationResult(
                        False,
                        "used",
                        EMAIL_VERIFICATION_USED_MESSAGE,
                        user_id=int(row["user_id"]),
                        email=row["email"],
                    )

                now = _now()
                if _coerce_datetime(row["expira_em"]) <= now:
                    return EmailVerificationResult(
                        False,
                        "expired",
                        EMAIL_VERIFICATION_INVALID_MESSAGE,
                        user_id=int(row["user_id"]),
                        email=row["email"],
                    )

                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                update_result = conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET email_verificado = :email_verificado,
                            email_verificado_em = :email_verificado_em,
                            atualizado_em = :atualizado_em
                        WHERE id = :user_id
                          AND {active_condition}
                        """
                    ),
                    {
                        "user_id": row["user_id"],
                        "email_verificado": True,
                        "email_verificado_em": now,
                        "atualizado_em": now,
                    },
                )
                if update_result.rowcount == 0:
                    return EmailVerificationResult(False, "invalid", EMAIL_VERIFICATION_INVALID_MESSAGE)

                conn.execute(
                    text(
                        """
                        UPDATE email_verification_tokens
                        SET usado_em = :usado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "usado_em": now},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=verify | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                detalhe="operacao=email_verification",
                status="failure",
                source="auth",
                action="database",
            )
            raise

        _log_audit_event(
            self.engine,
            "email_verification_completed",
            user_id=int(row["user_id"]),
            user_email=row["email"],
            detalhe="resultado=email_verificado",
            status="success",
            source="auth",
            action="email_verification",
        )
        return EmailVerificationResult(
            True,
            "verified",
            EMAIL_VERIFICATION_SUCCESS_MESSAGE,
            user_id=int(row["user_id"]),
            email=row["email"],
        )

    def is_email_verified(self, user_id: int) -> bool:
        try:
            with self.engine.connect() as conn:
                columns = _get_usuario_columns(conn)
                if "email_verificado" not in columns:
                    return False
                active_condition = _active_user_condition(columns)
                row = conn.execute(
                    text(
                        f"""
                        SELECT email_verificado
                        FROM usuarios
                        WHERE id = :id
                          AND {active_condition}
                        LIMIT 1
                        """
                    ),
                    {"id": user_id},
                ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=status | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return bool(row and row["email_verificado"])

    def mark_email_verified(self, user_id: int) -> None:
        try:
            with self.engine.begin() as conn:
                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                now = _now()
                conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET email_verificado = :email_verificado,
                            email_verificado_em = :email_verificado_em,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND {active_condition}
                        """
                    ),
                    {
                        "id": user_id,
                        "email_verificado": True,
                        "email_verificado_em": now,
                        "atualizado_em": now,
                    },
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro verificacao_email | acao=mark_verified | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def _get_active_user_email(self, conn: Any, user_id: int) -> str:
        active_condition = _active_user_condition(_get_usuario_columns(conn))
        row = conn.execute(
            text(
                f"""
                SELECT email
                FROM usuarios
                WHERE id = :id
                  AND {active_condition}
                LIMIT 1
                """
            ),
            {"id": user_id},
        ).mappings().first()

        return str(row["email"]) if row else ""

    def _build_verification_target(self, raw_token: str) -> str:
        if not self.app_public_url:
            return raw_token

        separator = "&" if "?" in self.app_public_url else "?"
        return f"{self.app_public_url}{separator}{urlencode({'verify_email_token': raw_token})}"
