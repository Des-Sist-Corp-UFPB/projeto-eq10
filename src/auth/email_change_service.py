"""Fluxo seguro para alteracao verificada de e-mail."""

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
from src.auth.security import verify_password
from src.auth.user_service import (
    AuthValidationError,
    UserProfile,
    _active_user_condition,
    _add_usuario_column_if_missing,
    _get_usuario_columns,
    _normalize_email,
    _now,
    _row_to_user,
    _validate_email,
    get_auth_engine,
    safe_auth_exception_summary,
)

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_CHANGE_TOKEN_TTL_HOURS = 24
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8501"

EMAIL_CHANGE_SENT_MESSAGE = "Enviamos um link de confirmacao para o novo e-mail."
EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE = (
    "O envio de e-mail ainda nao esta configurado. Nao foi possivel alterar o e-mail agora."
)
EMAIL_CHANGE_SEND_FAILED_MESSAGE = "Nao foi possivel enviar a confirmacao agora."
EMAIL_CHANGE_SUCCESS_MESSAGE = "E-mail alterado com sucesso."
EMAIL_CHANGE_INVALID_MESSAGE = "Link de alteracao de e-mail invalido ou expirado."
EMAIL_CHANGE_USED_MESSAGE = "Este link de alteracao de e-mail ja foi utilizado."
EMAIL_CHANGE_DUPLICATE_MESSAGE = "Nao foi possivel usar este e-mail."
EMAIL_CHANGE_SAME_EMAIL_MESSAGE = "Informe um e-mail diferente do atual."


def hash_email_change_token(raw_token: str) -> str:
    """Gera hash irreversivel do token de alteracao de e-mail."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EmailChangeToken:
    user_id: int
    current_email: str
    new_email: str
    raw_token: str
    expira_em: datetime


@dataclass(frozen=True)
class EmailChangeResult:
    success: bool
    status: str
    message: str
    user_id: int | None = None
    current_email: str | None = None
    new_email: str | None = None
    send_result: EmailSendResult | None = None
    token_created: bool = False
    user: UserProfile | None = None


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


def _strip_query_and_fragment(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _resolve_public_base_url(explicit_url: str | None = None) -> str:
    raw_url = (
        explicit_url
        or os.getenv("APP_PUBLIC_BASE_URL")
        or os.getenv("EMAIL_PUBLIC_BASE_URL")
        or os.getenv("APP_PUBLIC_URL")
        or DEFAULT_PUBLIC_BASE_URL
    ).strip()
    return _strip_query_and_fragment(raw_url).rstrip("/")


def _email_delivery_is_disabled(email_service: EmailService) -> bool:
    config = getattr(email_service, "config", None)
    if config is None:
        return False

    provider = str(getattr(config, "provider", "") or "").strip().lower()
    return not bool(getattr(config, "enabled", False)) or provider in {"fake", "local", "dev"}


class EmailChangeService:
    """Casos de uso para alteracao de e-mail com confirmacao no novo endereco."""

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        app_public_url: str | None = None,
        initialize_schema: bool = True,
        token_ttl_hours: int = DEFAULT_EMAIL_CHANGE_TOKEN_TTL_HOURS,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.app_public_url = _resolve_public_base_url(app_public_url)
        self.token_ttl_hours = token_ttl_hours
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "EmailChangeService":
        return cls(get_auth_engine(), email_service=EmailService.from_environment())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS email_change_tokens (
                {id_column},
                user_id INTEGER NOT NULL,
                novo_email TEXT NOT NULL,
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
                        CREATE UNIQUE INDEX IF NOT EXISTS ux_email_change_tokens_hash
                        ON email_change_tokens (token_hash)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_email_change_tokens_user
                        ON email_change_tokens (user_id)
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
                conn.execute(text("UPDATE usuarios SET email_verificado = false WHERE email_verificado IS NULL"))
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=ensure_schema | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def create_email_change_token(self, user_id: int, new_email: str) -> EmailChangeToken:
        clean_new_email = _validate_email(new_email)
        try:
            with self.engine.begin() as conn:
                user = self._get_active_user_with_password(conn, user_id)
                if user is None:
                    raise AuthValidationError("Usuario ativo nao encontrado.")
                current_email = str(user["email"])
                if _normalize_email(current_email) == clean_new_email:
                    raise AuthValidationError(EMAIL_CHANGE_SAME_EMAIL_MESSAGE)
                if self._active_email_used_by_other(conn, clean_new_email, user_id):
                    raise AuthValidationError(EMAIL_CHANGE_DUPLICATE_MESSAGE)

                raw_token = secrets.token_urlsafe(32)
                token_hash = hash_email_change_token(raw_token)
                now = _now()
                expira_em = now + timedelta(hours=self.token_ttl_hours)
                conn.execute(
                    text(
                        """
                        UPDATE email_change_tokens
                        SET usado_em = :usado_em
                        WHERE user_id = :user_id
                          AND usado_em IS NULL
                        """
                    ),
                    {"user_id": user_id, "usado_em": now},
                )
                conn.execute(
                    text(
                        """
                        INSERT INTO email_change_tokens (
                            user_id,
                            novo_email,
                            token_hash,
                            criado_em,
                            expira_em
                        )
                        VALUES (
                            :user_id,
                            :novo_email,
                            :token_hash,
                            :criado_em,
                            :expira_em
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "novo_email": clean_new_email,
                        "token_hash": token_hash,
                        "criado_em": now,
                        "expira_em": expira_em,
                    },
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=create_token | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        logger.info(
            "Token de alteracao de e-mail criado | user_id=%s | destinatario=%s",
            user_id,
            mask_email(clean_new_email),
        )
        return EmailChangeToken(
            user_id=user_id,
            current_email=current_email,
            new_email=clean_new_email,
            raw_token=raw_token,
            expira_em=expira_em,
        )

    def request_email_change(
        self,
        user_id: int,
        new_email: str,
        current_password: str,
    ) -> EmailChangeResult:
        clean_new_email = _validate_email(new_email)
        if not current_password:
            raise AuthValidationError("Informe sua senha atual.")

        try:
            with self.engine.connect() as conn:
                user = self._get_active_user_with_password(conn, user_id)
                if user is None:
                    raise AuthValidationError("Usuario ativo nao encontrado.")
                current_email = str(user["email"])
                if _normalize_email(current_email) == clean_new_email:
                    raise AuthValidationError(EMAIL_CHANGE_SAME_EMAIL_MESSAGE)
                if not verify_password(current_password, user["senha_hash"]):
                    raise AuthValidationError("Senha atual invalida.")
                if self._active_email_used_by_other(conn, clean_new_email, user_id):
                    return EmailChangeResult(
                        False,
                        "duplicate_email",
                        EMAIL_CHANGE_DUPLICATE_MESSAGE,
                        user_id=user_id,
                        current_email=current_email,
                        new_email=clean_new_email,
                    )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=request_validate | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        if _email_delivery_is_disabled(self.email_service):
            return EmailChangeResult(
                False,
                "email_disabled",
                EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE,
                user_id=user_id,
                current_email=current_email,
                new_email=clean_new_email,
            )

        try:
            token = self.create_email_change_token(user_id, clean_new_email)
            confirmation_target = self._build_confirmation_target(token.raw_token)
            send_result = self.email_service.send_email_change_confirmation_email(
                token.new_email,
                confirmation_target,
            )
        except AuthValidationError:
            raise
        except Exception as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=request_send | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            return EmailChangeResult(
                False,
                "send_failed",
                EMAIL_CHANGE_SEND_FAILED_MESSAGE,
                user_id=user_id,
                current_email=current_email,
                new_email=clean_new_email,
            )

        if send_result.success and send_result.sent:
            status = "sent"
            message = EMAIL_CHANGE_SENT_MESSAGE
            success = True
        elif send_result.mode == "fake" or (send_result.success and not send_result.sent):
            status = "email_disabled"
            message = EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE
            success = False
        else:
            status = "send_failed"
            message = EMAIL_CHANGE_SEND_FAILED_MESSAGE
            success = False

        logger.info(
            "Alteracao de e-mail solicitada | user_id=%s | destinatario=%s | modo=%s | sucesso=%s",
            user_id,
            mask_email(clean_new_email),
            send_result.mode,
            send_result.success,
        )
        return EmailChangeResult(
            success,
            status,
            message,
            user_id=user_id,
            current_email=current_email,
            new_email=clean_new_email,
            send_result=send_result,
            token_created=True,
        )

    def confirm_email_change_token(self, raw_token: str) -> EmailChangeResult:
        clean_token = (raw_token or "").strip()
        if not clean_token:
            return EmailChangeResult(False, "invalid", EMAIL_CHANGE_INVALID_MESSAGE)

        token_hash = hash_email_change_token(clean_token)
        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT id, user_id, novo_email, expira_em, usado_em
                        FROM email_change_tokens
                        WHERE token_hash = :token_hash
                        LIMIT 1
                        """
                    ),
                    {"token_hash": token_hash},
                ).mappings().first()

                if row is None:
                    return EmailChangeResult(False, "invalid", EMAIL_CHANGE_INVALID_MESSAGE)

                user_id = int(row["user_id"])
                new_email = str(row["novo_email"])
                user = self._get_active_user_with_password(conn, user_id)
                if user is None:
                    return EmailChangeResult(False, "invalid", EMAIL_CHANGE_INVALID_MESSAGE, user_id=user_id)

                if row["usado_em"] is not None:
                    return EmailChangeResult(
                        False,
                        "used",
                        EMAIL_CHANGE_USED_MESSAGE,
                        user_id=user_id,
                        current_email=str(user["email"]),
                        new_email=new_email,
                    )

                now = _now()
                if _coerce_datetime(row["expira_em"]) <= now:
                    return EmailChangeResult(
                        False,
                        "expired",
                        EMAIL_CHANGE_INVALID_MESSAGE,
                        user_id=user_id,
                        current_email=str(user["email"]),
                        new_email=new_email,
                    )

                if self._active_email_used_by_other(conn, new_email, user_id):
                    return EmailChangeResult(
                        False,
                        "duplicate_email",
                        EMAIL_CHANGE_DUPLICATE_MESSAGE,
                        user_id=user_id,
                        current_email=str(user["email"]),
                        new_email=new_email,
                    )

                columns = _get_usuario_columns(conn)
                active_condition = _active_user_condition(columns)
                update_result = conn.execute(
                    text(
                        f"""
                        UPDATE usuarios
                        SET email = :email,
                            email_verificado = :email_verificado,
                            email_verificado_em = :email_verificado_em,
                            atualizado_em = :atualizado_em
                        WHERE id = :user_id
                          AND {active_condition}
                        """
                    ),
                    {
                        "user_id": user_id,
                        "email": new_email,
                        "email_verificado": True,
                        "email_verificado_em": now,
                        "atualizado_em": now,
                    },
                )
                if update_result.rowcount == 0:
                    return EmailChangeResult(False, "invalid", EMAIL_CHANGE_INVALID_MESSAGE, user_id=user_id)

                conn.execute(
                    text(
                        """
                        UPDATE email_change_tokens
                        SET usado_em = :usado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": row["id"], "usado_em": now},
                )
                updated_user = conn.execute(
                    text(
                        """
                        SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em
                        FROM usuarios
                        WHERE id = :id
                        LIMIT 1
                        """
                    ),
                    {"id": user_id},
                ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=confirm | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return EmailChangeResult(
            True,
            "changed",
            EMAIL_CHANGE_SUCCESS_MESSAGE,
            user_id=user_id,
            current_email=str(user["email"]),
            new_email=new_email,
            user=_row_to_user(updated_user),
        )

    def _get_active_user_with_password(self, conn: Any, user_id: int) -> Any | None:
        active_condition = _active_user_condition(_get_usuario_columns(conn))
        return conn.execute(
            text(
                f"""
                SELECT id, nome, email, senha_hash
                FROM usuarios
                WHERE id = :id
                  AND {active_condition}
                LIMIT 1
                """
            ),
            {"id": user_id},
        ).mappings().first()

    def _active_email_used_by_other(self, conn: Any, email: str, user_id: int) -> bool:
        active_condition = _active_user_condition(_get_usuario_columns(conn))
        row = conn.execute(
            text(
                f"""
                SELECT id
                FROM usuarios
                WHERE lower(email) = :email
                  AND id <> :id
                  AND {active_condition}
                LIMIT 1
                """
            ),
            {"email": email, "id": user_id},
        ).mappings().first()
        return row is not None

    def _build_confirmation_target(self, raw_token: str) -> str:
        if not self.app_public_url:
            return raw_token

        separator = "&" if "?" in self.app_public_url else "?"
        return f"{self.app_public_url}{separator}{urlencode({'confirm_email_change_token': raw_token})}"
