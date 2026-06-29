"""Cadastro pendente por codigo de verificacao de e-mail."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from src.auth.email_service import EmailSendResult, EmailService, mask_email
from src.auth.security import hash_password
from src.auth.user_service import (
    AuthValidationError,
    UserProfile,
    _active_user_condition,
    _get_usuario_columns,
    _is_soft_deleted,
    _now,
    _row_to_user,
    _soft_delete_select_columns,
    _validate_email,
    _validate_name,
    _validate_new_password,
    get_auth_engine,
    safe_auth_exception_summary,
    UserService,
)

logger = logging.getLogger(__name__)

DEFAULT_REGISTRATION_CODE_TTL_MINUTES = 15
MAX_REGISTRATION_CODE_ATTEMPTS = 5

REGISTRATION_CODE_SENT_MESSAGE = "Enviamos um codigo de verificacao para seu e-mail."
REGISTRATION_EMAIL_DISABLED_MESSAGE = (
    "O envio de e-mail ainda nao esta configurado. Nao foi possivel concluir o cadastro agora."
)
REGISTRATION_EMAIL_SEND_FAILED_MESSAGE = "Nao foi possivel enviar o codigo de verificacao agora."
REGISTRATION_SUCCESS_MESSAGE = "E-mail confirmado. Sua conta foi criada."
REGISTRATION_ACTIVE_EMAIL_MESSAGE = "Ja existe uma conta ativa com este e-mail."
REGISTRATION_INVALID_CODE_MESSAGE = "Codigo invalido."
REGISTRATION_EXPIRED_CODE_MESSAGE = "Codigo expirado. Solicite um novo codigo."
REGISTRATION_TOO_MANY_ATTEMPTS_MESSAGE = "Muitas tentativas invalidas. Solicite um novo codigo."
REGISTRATION_DELETED_EMAIL_MESSAGE = "Nao foi possivel criar uma nova conta com este e-mail."


def generate_registration_code() -> str:
    """Gera codigo numerico de seis digitos com fonte segura."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_registration_code(raw_code: str) -> str:
    """Gera hash irreversivel do codigo de verificacao."""
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
        logger.debug("audit_log nao disponivel ainda - ignorado em cadastro_pendente")


@dataclass(frozen=True)
class PendingRegistrationResult:
    success: bool
    status: str
    message: str
    pending_registration_id: int | None = None
    email: str | None = None
    user: UserProfile | None = None
    send_result: EmailSendResult | None = None


class PendingRegistrationService:
    """Fluxo de cadastro com confirmacao por codigo antes de criar usuario."""

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        initialize_schema: bool = True,
        code_ttl_minutes: int = DEFAULT_REGISTRATION_CODE_TTL_MINUTES,
        max_attempts: int = MAX_REGISTRATION_CODE_ATTEMPTS,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.code_ttl_minutes = code_ttl_minutes
        self.max_attempts = max_attempts
        if initialize_schema:
            UserService(self.engine, initialize_schema=True)
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "PendingRegistrationService":
        return cls(get_auth_engine(), email_service=EmailService.from_environment())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS pending_registrations (
                {id_column},
                nome TEXT NOT NULL,
                email TEXT NOT NULL,
                senha_hash TEXT NOT NULL,
                codigo_hash TEXT NOT NULL,
                criado_em TIMESTAMP NOT NULL,
                expira_em TIMESTAMP NOT NULL,
                usado_em TIMESTAMP NULL,
                tentativas INTEGER NOT NULL DEFAULT 0,
                consumed_user_id INTEGER NULL
            )
        """

        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_table_sql))
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_pending_registrations_email
                        ON pending_registrations (lower(email))
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_pending_registrations_active
                        ON pending_registrations (email, usado_em, expira_em)
                        """
                    )
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro cadastro_pendente | acao=ensure_schema | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            raise

    def start_registration(
        self,
        nome: str,
        email: str,
        senha: str,
        confirmar_senha: str,
    ) -> PendingRegistrationResult:
        clean_name = _validate_name(nome)
        clean_email = _validate_email(email)
        clean_password = _validate_new_password(senha, confirmar_senha)
        password_hash = hash_password(clean_password)
        raw_code = generate_registration_code()
        code_hash = hash_registration_code(raw_code)
        now = _now()
        expires_at = now + timedelta(minutes=self.code_ttl_minutes)
        pending_id: int | None = None

        try:
            with self.engine.begin() as conn:
                email_status = self._get_email_registration_status(conn, clean_email)
                if email_status == "active":
                    return PendingRegistrationResult(
                        success=False,
                        status="active_email_exists",
                        message=REGISTRATION_ACTIVE_EMAIL_MESSAGE,
                        email=clean_email,
                    )
                if email_status == "deactivated":
                    return PendingRegistrationResult(
                        success=False,
                        status="deactivated_user_found",
                        message=REGISTRATION_DELETED_EMAIL_MESSAGE,
                        email=clean_email,
                    )
                self._consume_open_pending_registrations(conn, clean_email, now)
                conn.execute(
                    text(
                        """
                        INSERT INTO pending_registrations (
                            nome,
                            email,
                            senha_hash,
                            codigo_hash,
                            criado_em,
                            expira_em,
                            tentativas
                        )
                        VALUES (
                            :nome,
                            :email,
                            :senha_hash,
                            :codigo_hash,
                            :criado_em,
                            :expira_em,
                            0
                        )
                        """
                    ),
                    {
                        "nome": clean_name,
                        "email": clean_email,
                        "senha_hash": password_hash,
                        "codigo_hash": code_hash,
                        "criado_em": now,
                        "expira_em": expires_at,
                    },
                )
                row = conn.execute(
                    text(
                        """
                        SELECT id
                        FROM pending_registrations
                        WHERE lower(email) = :email
                          AND usado_em IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ),
                    {"email": clean_email},
                ).mappings().first()
                pending_id = int(row["id"])
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro cadastro_pendente | acao=start_registration | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=start_registration",
                status="failure",
                source="auth",
                action="database",
            )
            raise

        send_result = self._send_registration_code(clean_email, raw_code)
        if not send_result.sent:
            self._consume_pending_registration(pending_id)
            _log_audit_event(
                self.engine,
                "email_sending_failure",
                user_email=clean_email,
                detalhe=f"message_type=registration_verification_code; mode={send_result.mode}; error_code={send_result.error_code or 'email_not_sent'}",
                status="failure",
                source="email",
                action="registration_code",
            )
            message = (
                REGISTRATION_EMAIL_DISABLED_MESSAGE
                if send_result.mode == "fake" or send_result.error_code == "email_disabled"
                else REGISTRATION_EMAIL_SEND_FAILED_MESSAGE
            )
            return PendingRegistrationResult(
                success=False,
                status="email_not_sent",
                message=message,
                pending_registration_id=pending_id,
                email=clean_email,
                send_result=send_result,
            )

        logger.info(
            "Cadastro pendente enviado | email=%s | pending_id=%s | provider=%s | mode=%s",
            mask_email(clean_email),
            pending_id,
            send_result.provider,
            send_result.mode,
        )
        return PendingRegistrationResult(
            success=True,
            status="code_sent",
            message=REGISTRATION_CODE_SENT_MESSAGE,
            pending_registration_id=pending_id,
            email=clean_email,
            send_result=send_result,
        )

    def confirm_registration_code(
        self,
        pending_registration_id: int,
        email: str,
        code: str,
    ) -> PendingRegistrationResult:
        clean_email = _validate_email(email)
        clean_code = (code or "").strip().replace(" ", "")
        if not clean_code:
            return PendingRegistrationResult(False, "invalid_code", REGISTRATION_INVALID_CODE_MESSAGE)

        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM pending_registrations
                        WHERE id = :id
                          AND lower(email) = :email
                        LIMIT 1
                        """
                    ),
                    {"id": int(pending_registration_id), "email": clean_email},
                ).mappings().first()

                if not row:
                    return PendingRegistrationResult(False, "invalid_code", REGISTRATION_INVALID_CODE_MESSAGE)
                if row["usado_em"] is not None:
                    return PendingRegistrationResult(False, "used", REGISTRATION_INVALID_CODE_MESSAGE)

                now = _now()
                if int(row["tentativas"] or 0) >= self.max_attempts:
                    return PendingRegistrationResult(
                        False,
                        "too_many_attempts",
                        REGISTRATION_TOO_MANY_ATTEMPTS_MESSAGE,
                        pending_registration_id=int(row["id"]),
                        email=clean_email,
                    )

                if _coerce_datetime(row["expira_em"]) <= now:
                    return PendingRegistrationResult(
                        False,
                        "expired",
                        REGISTRATION_EXPIRED_CODE_MESSAGE,
                        pending_registration_id=int(row["id"]),
                        email=clean_email,
                    )

                if hash_registration_code(clean_code) != row["codigo_hash"]:
                    attempts = int(row["tentativas"] or 0) + 1
                    conn.execute(
                        text(
                            """
                            UPDATE pending_registrations
                            SET tentativas = :tentativas
                            WHERE id = :id
                            """
                        ),
                        {"id": int(row["id"]), "tentativas": attempts},
                    )
                    if attempts >= self.max_attempts:
                        return PendingRegistrationResult(
                            False,
                            "too_many_attempts",
                            REGISTRATION_TOO_MANY_ATTEMPTS_MESSAGE,
                            pending_registration_id=int(row["id"]),
                            email=clean_email,
                        )
                    return PendingRegistrationResult(
                        False,
                        "invalid_code",
                        REGISTRATION_INVALID_CODE_MESSAGE,
                        pending_registration_id=int(row["id"]),
                        email=clean_email,
                    )

                email_status = self._get_email_registration_status(conn, clean_email)
                if email_status == "active":
                    return PendingRegistrationResult(
                        False,
                        "active_email_exists",
                        REGISTRATION_ACTIVE_EMAIL_MESSAGE,
                        pending_registration_id=int(row["id"]),
                        email=clean_email,
                    )
                if email_status == "deactivated":
                    return PendingRegistrationResult(
                        False,
                        "deactivated_user_found",
                        REGISTRATION_DELETED_EMAIL_MESSAGE,
                        pending_registration_id=int(row["id"]),
                        email=clean_email,
                    )
                user = self._create_verified_user_from_pending(conn, row, now)
                conn.execute(
                    text(
                        """
                        UPDATE pending_registrations
                        SET usado_em = :usado_em,
                            consumed_user_id = :consumed_user_id
                        WHERE id = :id
                        """
                    ),
                    {"id": int(row["id"]), "usado_em": now, "consumed_user_id": user.id},
                )
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro cadastro_pendente | acao=confirm_registration_code | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )
            _log_audit_event(
                self.engine,
                "database_connection_failure",
                user_email=clean_email,
                detalhe="operacao=confirm_registration_code",
                status="failure",
                source="auth",
                action="database",
            )
            raise

        _log_audit_event(
            self.engine,
            "account_created",
            user_id=user.id,
            user_email=user.email,
            detalhe="provider=password; flow=pending_registration",
            status="success",
            source="auth",
            action="account_created",
        )
        return PendingRegistrationResult(
            success=True,
            status="created",
            message=REGISTRATION_SUCCESS_MESSAGE,
            pending_registration_id=pending_registration_id,
            email=clean_email,
            user=user,
        )

    def _send_registration_code(self, email: str, code: str) -> EmailSendResult:
        body_text = (
            "Seu codigo de verificacao do SIA/DATASUS e:\n\n"
            f"{code}\n\n"
            f"Este codigo expira em {self.code_ttl_minutes} minutos. "
            "Se voce nao solicitou esta acao, ignore esta mensagem."
        )
        safe_code = escape(code, quote=True)
        body_html = (
            "<p>Seu codigo de verificacao do SIA/DATASUS e:</p>"
            f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{safe_code}</p>"
            f"<p>Este codigo expira em {self.code_ttl_minutes} minutos.</p>"
            "<p>Se voce nao solicitou esta acao, ignore esta mensagem.</p>"
        )
        return self.email_service.send_email(
            email,
            "Codigo de verificacao",
            body_text,
            body_html,
            message_type="registration_verification_code",
        )

    def _consume_pending_registration(self, pending_id: int | None) -> None:
        if pending_id is None:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pending_registrations
                        SET usado_em = :usado_em
                        WHERE id = :id
                          AND usado_em IS NULL
                        """
                    ),
                    {"id": int(pending_id), "usado_em": _now()},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro cadastro_pendente | acao=consume_pending | causa=%s | tipo=%s",
                safe_auth_exception_summary(exc),
                type(exc).__name__,
            )

    def _consume_open_pending_registrations(self, conn: Any, email: str, now: datetime) -> None:
        conn.execute(
            text(
                """
                UPDATE pending_registrations
                SET usado_em = :usado_em
                WHERE lower(email) = :email
                  AND usado_em IS NULL
                """
            ),
            {"email": email, "usado_em": now},
        )

    def _get_email_registration_status(self, conn: Any, email: str) -> str:
        columns = _get_usuario_columns(conn)
        active_condition = _active_user_condition(columns)
        soft_delete_columns = _soft_delete_select_columns(columns)
        row = conn.execute(
            text(
                f"""
                SELECT id, {soft_delete_columns}
                FROM usuarios
                WHERE lower(email) = :email
                ORDER BY CASE WHEN {active_condition} THEN 1 ELSE 0 END DESC, id DESC
                LIMIT 1
                """
            ),
            {"email": email},
        ).mappings().first()

        if not row:
            return "none"
        if _is_soft_deleted(row):
            return "deactivated"
        return "active"

    def _create_verified_user_from_pending(
        self,
        conn: Any,
        pending_row: Any,
        now: datetime,
    ) -> UserProfile:
        try:
            conn.execute(
                text(
                    """
                    INSERT INTO usuarios (
                        nome,
                        email,
                        senha_hash,
                        role,
                        criado_em,
                        atualizado_em,
                        email_verificado,
                        email_verificado_em,
                        deletado,
                        deletado_em
                    )
                    VALUES (
                        :nome,
                        :email,
                        :senha_hash,
                        'user',
                        :criado_em,
                        :atualizado_em,
                        :email_verificado,
                        :email_verificado_em,
                        :deletado,
                        :deletado_em
                    )
                    """
                ),
                {
                    "nome": pending_row["nome"],
                    "email": pending_row["email"],
                    "senha_hash": pending_row["senha_hash"],
                    "criado_em": now,
                    "atualizado_em": now,
                    "email_verificado": True,
                    "email_verificado_em": now,
                    "deletado": False,
                    "deletado_em": None,
                },
            )
        except IntegrityError as exc:
            raise AuthValidationError("Ja existe uma conta ativa com este e-mail.") from exc

        active_condition = _active_user_condition(_get_usuario_columns(conn))
        user_row = conn.execute(
            text(
                f"""
                SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em
                FROM usuarios
                WHERE lower(email) = :email
                  AND {active_condition}
                ORDER BY id DESC
                LIMIT 1
                """
            ),
            {"email": pending_row["email"]},
        ).mappings().first()
        return _row_to_user(user_row)
