"""Reativacao segura de contas desativadas por soft delete."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.auth.email_service import EmailSendResult, EmailService, mask_email
from src.auth.user_service import (
    UserProfile,
    _active_user_condition,
    _get_usuario_columns,
    _is_soft_deleted,
    _now,
    _row_to_user,
    _soft_delete_select_columns,
    _validate_email,
    get_auth_engine,
    safe_auth_exception_summary,
    UserService,
)

logger = logging.getLogger(__name__)

ACCOUNT_REACTIVATION_WINDOW_DAYS_ENV = "ACCOUNT_REACTIVATION_WINDOW_DAYS"
DEFAULT_ACCOUNT_REACTIVATION_WINDOW_DAYS = 90
DEFAULT_ACCOUNT_REACTIVATION_CODE_TTL_MINUTES = 15
MAX_ACCOUNT_REACTIVATION_ATTEMPTS = 5

ACCOUNT_REACTIVATION_NEUTRAL_MESSAGE = (
    "Se for possivel continuar com este e-mail, enviaremos instrucoes para ele."
)
ACCOUNT_REACTIVATION_CODE_SENT_MESSAGE = "Enviamos um codigo de reativacao para seu e-mail."
ACCOUNT_REACTIVATION_EMAIL_DISABLED_MESSAGE = (
    "O envio de e-mail ainda nao esta configurado. Nao foi possivel continuar agora."
)
ACCOUNT_REACTIVATION_SEND_FAILED_MESSAGE = "Nao foi possivel enviar a reativacao agora."
ACCOUNT_REACTIVATION_SUCCESS_MESSAGE = "Conta reativada com sucesso. Voce ja pode entrar."
ACCOUNT_REACTIVATION_INVALID_CODE_MESSAGE = "Codigo invalido."
ACCOUNT_REACTIVATION_EXPIRED_CODE_MESSAGE = "Codigo expirado. Solicite um novo codigo."
ACCOUNT_REACTIVATION_USED_CODE_MESSAGE = "Este codigo de reativacao ja foi utilizado."
ACCOUNT_REACTIVATION_TOO_MANY_ATTEMPTS_MESSAGE = (
    "Muitas tentativas invalidas. Solicite um novo codigo."
)
ACCOUNT_REACTIVATION_WINDOW_EXPIRED_MESSAGE = "Nao foi possivel reativar esta conta automaticamente."


def get_account_reactivation_window_days() -> int:
    raw_value = os.getenv(ACCOUNT_REACTIVATION_WINDOW_DAYS_ENV, "").strip()
    if not raw_value:
        return DEFAULT_ACCOUNT_REACTIVATION_WINDOW_DAYS
    try:
        days = int(raw_value)
    except ValueError:
        return DEFAULT_ACCOUNT_REACTIVATION_WINDOW_DAYS
    return days if days > 0 else DEFAULT_ACCOUNT_REACTIVATION_WINDOW_DAYS


def generate_reactivation_code() -> str:
    """Gera codigo numerico de seis digitos com fonte segura."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_reactivation_code(raw_code: str) -> str:
    """Gera hash irreversivel do codigo de reativacao."""
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


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
        logger.debug("audit_log nao disponivel ainda - ignorado em reativacao_conta")


@dataclass(frozen=True)
class AccountReactivationResult:
    success: bool
    status: str
    message: str
    reactivation_token_id: int | None = None
    email: str | None = None
    user: UserProfile | None = None
    send_result: EmailSendResult | None = None


class AccountReactivationService:
    """Cria e valida codigo para reabrir conta desativada."""

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        initialize_schema: bool = True,
        code_ttl_minutes: int = DEFAULT_ACCOUNT_REACTIVATION_CODE_TTL_MINUTES,
        max_attempts: int = MAX_ACCOUNT_REACTIVATION_ATTEMPTS,
        window_days: int | None = None,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.code_ttl_minutes = code_ttl_minutes
        self.max_attempts = max_attempts
        self.window_days = window_days or get_account_reactivation_window_days()
        if initialize_schema:
            UserService(self.engine, initialize_schema=True)
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "AccountReactivationService":
        return cls(get_auth_engine(), email_service=EmailService.from_environment())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS account_reactivation_tokens (
                {id_column},
                user_id INTEGER NOT NULL,
                codigo_hash TEXT NOT NULL,
                criado_em TIMESTAMP NOT NULL,
                expira_em TIMESTAMP NOT NULL,
                usado_em TIMESTAMP NULL,
                tentativas INTEGER NOT NULL DEFAULT 0
            )
        """

        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_table_sql))
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_account_reactivation_tokens_user
                        ON account_reactivation_tokens (user_id)
                        """
                    )
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro reativacao_conta | acao=ensure_schema | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            raise

    def request_reactivation(self, email: str) -> AccountReactivationResult:
        clean_email = _validate_email(email)
        now = _now()
        raw_code = generate_reactivation_code()
        code_hash = hash_reactivation_code(raw_code)
        token_id: int | None = None
        user_id: int | None = None

        try:
            with self.engine.begin() as conn:
                user_row = self._get_user_by_email(conn, clean_email)
                if not user_row or not _is_soft_deleted(user_row):
                    return AccountReactivationResult(
                        True,
                        "not_applicable",
                        ACCOUNT_REACTIVATION_NEUTRAL_MESSAGE,
                        email=clean_email,
                    )

                if not self._is_within_reactivation_window(user_row, now):
                    return AccountReactivationResult(
                        False,
                        "window_expired",
                        ACCOUNT_REACTIVATION_WINDOW_EXPIRED_MESSAGE,
                        email=clean_email,
                    )

                user_id = int(user_row["id"])
                self._consume_open_reactivation_tokens(conn, user_id, now)
                expires_at = now + timedelta(minutes=self.code_ttl_minutes)
                conn.execute(
                    text(
                        """
                        INSERT INTO account_reactivation_tokens (
                            user_id,
                            codigo_hash,
                            criado_em,
                            expira_em,
                            tentativas
                        )
                        VALUES (
                            :user_id,
                            :codigo_hash,
                            :criado_em,
                            :expira_em,
                            0
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "codigo_hash": code_hash,
                        "criado_em": now,
                        "expira_em": expires_at,
                    },
                )
                row = conn.execute(
                    text(
                        """
                        SELECT id
                        FROM account_reactivation_tokens
                        WHERE user_id = :user_id
                          AND usado_em IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id},
                ).mappings().first()
                token_id = int(row["id"])
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro reativacao_conta | acao=request_reactivation | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            raise

        send_result = self._send_reactivation_code(clean_email, raw_code)
        if not send_result.sent:
            self._consume_reactivation_token(token_id)
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_id=user_id,
                user_email=clean_email,
                detalhe=f"message_type=account_reactivation_code; mode={send_result.mode}; error_code={send_result.error_code or 'email_not_sent'}",
                status="failure",
                source="email",
                action="account_reactivation",
            )
            message = (
                ACCOUNT_REACTIVATION_EMAIL_DISABLED_MESSAGE
                if send_result.mode == "fake" or send_result.error_code == "email_disabled"
                else ACCOUNT_REACTIVATION_SEND_FAILED_MESSAGE
            )
            return AccountReactivationResult(
                False,
                "email_not_sent",
                message,
                reactivation_token_id=token_id,
                email=clean_email,
                send_result=send_result,
            )

        logger.info(
            "Reativacao enviada | email=%s | user_id=%s | token_id=%s | provider=%s | mode=%s",
            mask_email(clean_email),
            user_id,
            token_id,
            send_result.provider,
            send_result.mode,
        )
        return AccountReactivationResult(
            True,
            "code_sent",
            ACCOUNT_REACTIVATION_CODE_SENT_MESSAGE,
            reactivation_token_id=token_id,
            email=clean_email,
            send_result=send_result,
        )

    def confirm_reactivation_code(
        self,
        reactivation_token_id: int,
        email: str,
        code: str,
    ) -> AccountReactivationResult:
        clean_email = _validate_email(email)
        clean_code = (code or "").strip().replace(" ", "")
        if not clean_code:
            return AccountReactivationResult(False, "invalid_code", ACCOUNT_REACTIVATION_INVALID_CODE_MESSAGE)

        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT t.*, u.email, u.nome, u.role, u.criado_em, u.atualizado_em,
                               u.ultimo_login_em,
                               u.deleted_at, u.deletado, u.deletado_em
                        FROM account_reactivation_tokens t
                        JOIN usuarios u ON u.id = t.user_id
                        WHERE t.id = :id
                          AND lower(u.email) = :email
                        LIMIT 1
                        """
                    ),
                    {"id": int(reactivation_token_id), "email": clean_email},
                ).mappings().first()

                if not row:
                    return AccountReactivationResult(False, "invalid_code", ACCOUNT_REACTIVATION_INVALID_CODE_MESSAGE)
                if row["usado_em"] is not None:
                    return AccountReactivationResult(False, "used", ACCOUNT_REACTIVATION_USED_CODE_MESSAGE)

                now = _now()
                if int(row["tentativas"] or 0) >= self.max_attempts:
                    return AccountReactivationResult(
                        False,
                        "too_many_attempts",
                        ACCOUNT_REACTIVATION_TOO_MANY_ATTEMPTS_MESSAGE,
                        reactivation_token_id=int(row["id"]),
                        email=clean_email,
                    )
                if _coerce_datetime(row["expira_em"]) <= now:
                    return AccountReactivationResult(
                        False,
                        "expired",
                        ACCOUNT_REACTIVATION_EXPIRED_CODE_MESSAGE,
                        reactivation_token_id=int(row["id"]),
                        email=clean_email,
                    )
                if not _is_soft_deleted(row) or not self._is_within_reactivation_window(row, now):
                    return AccountReactivationResult(
                        False,
                        "window_expired",
                        ACCOUNT_REACTIVATION_WINDOW_EXPIRED_MESSAGE,
                        reactivation_token_id=int(row["id"]),
                        email=clean_email,
                    )

                if hash_reactivation_code(clean_code) != row["codigo_hash"]:
                    attempts = int(row["tentativas"] or 0) + 1
                    conn.execute(
                        text(
                            """
                            UPDATE account_reactivation_tokens
                            SET tentativas = :tentativas
                            WHERE id = :id
                            """
                        ),
                        {"id": int(row["id"]), "tentativas": attempts},
                    )
                    if attempts >= self.max_attempts:
                        return AccountReactivationResult(
                            False,
                            "too_many_attempts",
                            ACCOUNT_REACTIVATION_TOO_MANY_ATTEMPTS_MESSAGE,
                            reactivation_token_id=int(row["id"]),
                            email=clean_email,
                        )
                    return AccountReactivationResult(
                        False,
                        "invalid_code",
                        ACCOUNT_REACTIVATION_INVALID_CODE_MESSAGE,
                        reactivation_token_id=int(row["id"]),
                        email=clean_email,
                    )

                user = self._reactivate_user(conn, int(row["user_id"]), now)
                conn.execute(
                    text(
                        """
                        UPDATE account_reactivation_tokens
                        SET usado_em = :usado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": int(row["id"]), "usado_em": now},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro reativacao_conta | acao=confirm_reactivation_code | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=account_reactivation_confirm",
                status="failure",
                source="auth",
                action="database",
            )
            raise

        _log_audit_event(
            self.engine,
            "account_reactivated",
            user_id=user.id if user else None,
            user_email=user.email if user else clean_email,
            detalhe="resultado=conta_reativada",
            status="success",
            source="auth",
            action="account_reactivation",
        )
        return AccountReactivationResult(
            True,
            "reactivated",
            ACCOUNT_REACTIVATION_SUCCESS_MESSAGE,
            reactivation_token_id=reactivation_token_id,
            email=clean_email,
            user=user,
        )

    def _get_user_by_email(self, conn: Any, email: str) -> Any | None:
        columns = _get_usuario_columns(conn)
        active_condition = _active_user_condition(columns)
        soft_delete_columns = _soft_delete_select_columns(columns)
        return conn.execute(
            text(
                f"""
                SELECT id, email, nome, role, criado_em, atualizado_em, ultimo_login_em,
                       {soft_delete_columns}
                FROM usuarios
                WHERE lower(email) = :email
                ORDER BY CASE WHEN {active_condition} THEN 1 ELSE 0 END DESC, id DESC
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()

    def _is_within_reactivation_window(self, row: Any, now: datetime) -> bool:
        deactivated_at = row["deletado_em"] or row["deleted_at"]
        if deactivated_at is None:
            return True

        return _coerce_datetime(deactivated_at) >= now - timedelta(days=self.window_days)

    def _send_reactivation_code(self, email: str, code: str) -> EmailSendResult:
        body_text = (
            "Seu codigo de reativacao do SIA/DATASUS e:\n\n"
            f"{code}\n\n"
            f"Este codigo expira em {self.code_ttl_minutes} minutos. "
            "Se voce nao solicitou esta acao, ignore esta mensagem."
        )
        safe_code = escape(code, quote=True)
        body_html = (
            "<p>Seu codigo de reativacao do SIA/DATASUS e:</p>"
            f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{safe_code}</p>"
            f"<p>Este codigo expira em {self.code_ttl_minutes} minutos.</p>"
            "<p>Se voce nao solicitou esta acao, ignore esta mensagem.</p>"
        )
        return self.email_service.send_email(
            email,
            "Codigo de reativacao de conta",
            body_text,
            body_html,
            message_type="account_reactivation_code",
        )

    def _consume_open_reactivation_tokens(self, conn: Any, user_id: int, now: datetime) -> None:
        conn.execute(
            text(
                """
                UPDATE account_reactivation_tokens
                SET usado_em = :usado_em
                WHERE user_id = :user_id
                  AND usado_em IS NULL
                """
            ),
            {"user_id": user_id, "usado_em": now},
        )

    def _consume_reactivation_token(self, token_id: int | None) -> None:
        if token_id is None:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE account_reactivation_tokens
                        SET usado_em = :usado_em
                        WHERE id = :id
                          AND usado_em IS NULL
                        """
                    ),
                    {"id": int(token_id), "usado_em": _now()},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro reativacao_conta | acao=consume_token | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )

    def _reactivate_user(self, conn: Any, user_id: int, now: datetime) -> UserProfile:
        columns = _get_usuario_columns(conn)
        assignments = ["atualizado_em = :atualizado_em"]
        params: dict[str, Any] = {"id": user_id, "atualizado_em": now}
        if "deleted_at" in columns:
            assignments.append("deleted_at = NULL")
        if "deletado" in columns:
            assignments.append("deletado = :deletado")
            params["deletado"] = False
        if "deletado_em" in columns:
            assignments.append("deletado_em = NULL")
        if "email_verificado" in columns:
            assignments.append("email_verificado = :email_verificado")
            params["email_verificado"] = True
        if "email_verificado_em" in columns:
            assignments.append("email_verificado_em = :email_verificado_em")
            params["email_verificado_em"] = now

        conn.execute(
            text(
                f"""
                UPDATE usuarios
                SET {", ".join(assignments)}
                WHERE id = :id
                """
            ),
            params,
        )
        row = conn.execute(
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
        return _row_to_user(row)
