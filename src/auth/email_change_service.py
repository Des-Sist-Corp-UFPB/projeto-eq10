"""Fluxo seguro para alteracao de e-mail por codigo."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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
    UserService,
)

logger = logging.getLogger(__name__)

DEFAULT_EMAIL_CHANGE_CODE_TTL_MINUTES = 15
MAX_EMAIL_CHANGE_CODE_ATTEMPTS = 5

EMAIL_CHANGE_CODE_SENT_MESSAGE = "Enviamos um codigo de confirmacao para o novo e-mail."
EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE = (
    "O envio de e-mail ainda nao esta configurado. Nao foi possivel alterar o e-mail agora."
)
EMAIL_CHANGE_SEND_FAILED_MESSAGE = "Nao foi possivel enviar a confirmacao agora."
EMAIL_CHANGE_SUCCESS_MESSAGE = "E-mail alterado com sucesso."
EMAIL_CHANGE_INVALID_CODE_MESSAGE = "Codigo invalido."
EMAIL_CHANGE_EXPIRED_CODE_MESSAGE = "Codigo expirado. Solicite um novo codigo."
EMAIL_CHANGE_USED_CODE_MESSAGE = "Este codigo de alteracao de e-mail ja foi utilizado."
EMAIL_CHANGE_TOO_MANY_ATTEMPTS_MESSAGE = "Muitas tentativas invalidas. Solicite um novo codigo."
EMAIL_CHANGE_DUPLICATE_MESSAGE = "Nao foi possivel usar este e-mail."
EMAIL_CHANGE_SAME_EMAIL_MESSAGE = "Informe um e-mail diferente do atual."


def generate_email_change_code() -> str:
    """Gera codigo numerico de seis digitos com fonte segura."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_email_change_code(raw_code: str) -> str:
    """Gera hash irreversivel do codigo de alteracao de e-mail."""
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


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


def _email_delivery_is_disabled(email_service: EmailService) -> bool:
    config = getattr(email_service, "config", None)
    if config is None:
        return False

    provider = str(getattr(config, "provider", "") or "").strip().lower()
    return not bool(getattr(config, "enabled", False)) or provider in {"fake", "local", "dev"}


@dataclass(frozen=True)
class PendingEmailChange:
    id: int
    user_id: int
    current_email: str
    new_email: str
    raw_code: str
    expira_em: datetime


@dataclass(frozen=True)
class EmailChangeResult:
    success: bool
    status: str
    message: str
    pending_change_id: int | None = None
    user_id: int | None = None
    current_email: str | None = None
    new_email: str | None = None
    send_result: EmailSendResult | None = None
    user: UserProfile | None = None


class EmailChangeService:
    """Casos de uso para alteracao de e-mail com codigo no novo endereco."""

    def __init__(
        self,
        engine,
        *,
        email_service: EmailService | None = None,
        initialize_schema: bool = True,
        code_ttl_minutes: int = DEFAULT_EMAIL_CHANGE_CODE_TTL_MINUTES,
        max_attempts: int = MAX_EMAIL_CHANGE_CODE_ATTEMPTS,
    ):
        self.engine = engine
        self.email_service = email_service or EmailService.from_environment()
        self.code_ttl_minutes = code_ttl_minutes
        self.max_attempts = max_attempts
        if initialize_schema:
            UserService(self.engine, initialize_schema=True)
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
            CREATE TABLE IF NOT EXISTS pending_email_changes (
                {id_column},
                user_id INTEGER NOT NULL,
                novo_email TEXT NOT NULL,
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
                        CREATE INDEX IF NOT EXISTS ix_pending_email_changes_user
                        ON pending_email_changes (user_id)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_pending_email_changes_active
                        ON pending_email_changes (user_id, usado_em, expira_em)
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
            pending_change = self.create_pending_email_change(user_id, clean_new_email)
            send_result = self._send_email_change_code(pending_change.new_email, pending_change.raw_code)
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

        if not send_result.sent:
            self._consume_pending_email_change(pending_change.id)
            message = (
                EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE
                if send_result.mode == "fake" or send_result.error_code == "email_disabled"
                else EMAIL_CHANGE_SEND_FAILED_MESSAGE
            )
            status = "email_disabled" if message == EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE else "send_failed"
            return EmailChangeResult(
                False,
                status,
                message,
                pending_change_id=pending_change.id,
                user_id=user_id,
                current_email=pending_change.current_email,
                new_email=pending_change.new_email,
                send_result=send_result,
            )

        logger.info(
            "Codigo de alteracao de e-mail enviado | user_id=%s | destinatario=%s | pending_id=%s | provider=%s | mode=%s",
            user_id,
            mask_email(clean_new_email),
            pending_change.id,
            send_result.provider,
            send_result.mode,
        )
        return EmailChangeResult(
            True,
            "code_sent",
            EMAIL_CHANGE_CODE_SENT_MESSAGE,
            pending_change_id=pending_change.id,
            user_id=user_id,
            current_email=pending_change.current_email,
            new_email=pending_change.new_email,
            send_result=send_result,
        )

    def create_pending_email_change(self, user_id: int, new_email: str) -> PendingEmailChange:
        clean_new_email = _validate_email(new_email)
        raw_code = generate_email_change_code()
        code_hash = hash_email_change_code(raw_code)
        now = _now()
        expires_at = now + timedelta(minutes=self.code_ttl_minutes)
        pending_id: int | None = None

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

                self._consume_open_pending_email_changes(conn, user_id, now)
                conn.execute(
                    text(
                        """
                        INSERT INTO pending_email_changes (
                            user_id,
                            novo_email,
                            codigo_hash,
                            criado_em,
                            expira_em,
                            tentativas
                        )
                        VALUES (
                            :user_id,
                            :novo_email,
                            :codigo_hash,
                            :criado_em,
                            :expira_em,
                            0
                        )
                        """
                    ),
                    {
                        "user_id": user_id,
                        "novo_email": clean_new_email,
                        "codigo_hash": code_hash,
                        "criado_em": now,
                        "expira_em": expires_at,
                    },
                )
                row = conn.execute(
                    text(
                        """
                        SELECT id
                        FROM pending_email_changes
                        WHERE user_id = :user_id
                          AND usado_em IS NULL
                        ORDER BY id DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": user_id},
                ).mappings().first()
                pending_id = int(row["id"])
        except AuthValidationError:
            raise
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=create_pending | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        logger.info(
            "Alteracao de e-mail pendente criada | user_id=%s | destinatario=%s | pending_id=%s",
            user_id,
            mask_email(clean_new_email),
            pending_id,
        )
        return PendingEmailChange(
            id=int(pending_id),
            user_id=user_id,
            current_email=current_email,
            new_email=clean_new_email,
            raw_code=raw_code,
            expira_em=expires_at,
        )

    def confirm_email_change_code(
        self,
        pending_change_id: int,
        user_id: int,
        code: str,
    ) -> EmailChangeResult:
        clean_code = (code or "").strip().replace(" ", "")
        if not clean_code:
            return EmailChangeResult(False, "invalid_code", EMAIL_CHANGE_INVALID_CODE_MESSAGE)

        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    text(
                        """
                        SELECT *
                        FROM pending_email_changes
                        WHERE id = :id
                          AND user_id = :user_id
                        LIMIT 1
                        """
                    ),
                    {"id": int(pending_change_id), "user_id": int(user_id)},
                ).mappings().first()

                if not row:
                    return EmailChangeResult(False, "invalid_code", EMAIL_CHANGE_INVALID_CODE_MESSAGE)

                user = self._get_active_user_with_password(conn, int(user_id))
                if user is None:
                    return EmailChangeResult(False, "invalid_code", EMAIL_CHANGE_INVALID_CODE_MESSAGE)

                current_email = str(user["email"])
                new_email = str(row["novo_email"])
                if row["usado_em"] is not None:
                    return EmailChangeResult(
                        False,
                        "used",
                        EMAIL_CHANGE_USED_CODE_MESSAGE,
                        pending_change_id=int(row["id"]),
                        user_id=int(user_id),
                        current_email=current_email,
                        new_email=new_email,
                    )

                now = _now()
                if int(row["tentativas"] or 0) >= self.max_attempts:
                    return EmailChangeResult(
                        False,
                        "too_many_attempts",
                        EMAIL_CHANGE_TOO_MANY_ATTEMPTS_MESSAGE,
                        pending_change_id=int(row["id"]),
                        user_id=int(user_id),
                        current_email=current_email,
                        new_email=new_email,
                    )

                if _coerce_datetime(row["expira_em"]) <= now:
                    return EmailChangeResult(
                        False,
                        "expired",
                        EMAIL_CHANGE_EXPIRED_CODE_MESSAGE,
                        pending_change_id=int(row["id"]),
                        user_id=int(user_id),
                        current_email=current_email,
                        new_email=new_email,
                    )

                if self._active_email_used_by_other(conn, new_email, int(user_id)):
                    return EmailChangeResult(
                        False,
                        "duplicate_email",
                        EMAIL_CHANGE_DUPLICATE_MESSAGE,
                        pending_change_id=int(row["id"]),
                        user_id=int(user_id),
                        current_email=current_email,
                        new_email=new_email,
                    )

                if hash_email_change_code(clean_code) != row["codigo_hash"]:
                    attempts = int(row["tentativas"] or 0) + 1
                    conn.execute(
                        text(
                            """
                            UPDATE pending_email_changes
                            SET tentativas = :tentativas
                            WHERE id = :id
                            """
                        ),
                        {"id": int(row["id"]), "tentativas": attempts},
                    )
                    if attempts >= self.max_attempts:
                        return EmailChangeResult(
                            False,
                            "too_many_attempts",
                            EMAIL_CHANGE_TOO_MANY_ATTEMPTS_MESSAGE,
                            pending_change_id=int(row["id"]),
                            user_id=int(user_id),
                            current_email=current_email,
                            new_email=new_email,
                        )
                    return EmailChangeResult(
                        False,
                        "invalid_code",
                        EMAIL_CHANGE_INVALID_CODE_MESSAGE,
                        pending_change_id=int(row["id"]),
                        user_id=int(user_id),
                        current_email=current_email,
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
                        "user_id": int(user_id),
                        "email": new_email,
                        "email_verificado": True,
                        "email_verificado_em": now,
                        "atualizado_em": now,
                    },
                )
                if update_result.rowcount == 0:
                    return EmailChangeResult(False, "invalid_code", EMAIL_CHANGE_INVALID_CODE_MESSAGE)

                conn.execute(
                    text(
                        """
                        UPDATE pending_email_changes
                        SET usado_em = :usado_em
                        WHERE id = :id
                        """
                    ),
                    {"id": int(row["id"]), "usado_em": now},
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
                    {"id": int(user_id)},
                ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=confirm_code | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return EmailChangeResult(
            True,
            "changed",
            EMAIL_CHANGE_SUCCESS_MESSAGE,
            pending_change_id=int(pending_change_id),
            user_id=int(user_id),
            current_email=current_email,
            new_email=new_email,
            user=_row_to_user(updated_user),
        )

    def _send_email_change_code(self, email: str, code: str) -> EmailSendResult:
        if hasattr(self.email_service, "send_email_change_code_email"):
            return self.email_service.send_email_change_code_email(
                email,
                code,
                expires_in_minutes=self.code_ttl_minutes,
            )

        return self.email_service.send_email(
            email,
            "Codigo para alterar seu e-mail",
            (
                "Seu codigo para alterar o e-mail da conta SIA/DATASUS e:\n\n"
                f"{code}\n\n"
                f"Este codigo expira em {self.code_ttl_minutes} minutos. "
                "O e-mail da conta so sera alterado depois da confirmacao. "
                "Se voce nao solicitou esta acao, ignore esta mensagem."
            ),
            message_type="email_change_code",
        )

    def _consume_open_pending_email_changes(self, conn: Any, user_id: int, now: datetime) -> None:
        conn.execute(
            text(
                """
                UPDATE pending_email_changes
                SET usado_em = :usado_em
                WHERE user_id = :user_id
                  AND usado_em IS NULL
                """
            ),
            {"user_id": int(user_id), "usado_em": now},
        )

    def _consume_pending_email_change(self, pending_change_id: int | None) -> None:
        if pending_change_id is None:
            return
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        UPDATE pending_email_changes
                        SET usado_em = :usado_em
                        WHERE id = :id
                          AND usado_em IS NULL
                        """
                    ),
                    {"id": int(pending_change_id), "usado_em": _now()},
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro alteracao_email | acao=consume_pending | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
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
