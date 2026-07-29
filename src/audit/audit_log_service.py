"""Servico de auditoria: persiste eventos de seguranca e uso do sistema."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from src.auth.user_service import run_transient_db_operation
from src.observability.telemetry import traced_operation

logger = logging.getLogger(__name__)

# Tipos de evento suportados.
EVENT_LOGIN = "login"
EVENT_LOGIN_FAILURE = "login_failure"
EVENT_LOGOUT = "logout"
EVENT_ACCOUNT_CREATED = "account_created"
EVENT_ACCOUNT_DELETED = "account_deleted"
EVENT_ACCOUNT_REACTIVATED = "account_reactivated"
EVENT_PASSWORD_RESET_REQUESTED = "password_reset_requested"
EVENT_PASSWORD_RESET_COMPLETED = "password_reset_completed"
EVENT_EMAIL_CHANGE_REQUESTED = "email_change_requested"
EVENT_EMAIL_CHANGE_CONFIRMED = "email_change_confirmed"
EVENT_EMAIL_VERIFICATION_COMPLETED = "email_verification_completed"
EVENT_CHAT_PROMPT = "chat_prompt"
EVENT_PROMPT_GUARD_BLOCK = "prompt_guard_block"
EVENT_CHAT_PROCESSING_ERROR = "chat_processing_error"
EVENT_ACCESS_GRANTED = "access_granted"
EVENT_ACCESS_REVOKED = "access_revoked"
EVENT_ROLE_CHANGED = "role_changed"
EVENT_ADMIN_ACCESS_DENIED = "admin_access_denied"
EVENT_DATABASE_CONNECTION_FAILURE = "database_connection_failure"
EVENT_EMAIL_SENDING_FAILURE = "email_sending_failure"

VALID_EVENTS = {
    EVENT_LOGIN,
    EVENT_LOGIN_FAILURE,
    EVENT_LOGOUT,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_ACCOUNT_REACTIVATED,
    EVENT_PASSWORD_RESET_REQUESTED,
    EVENT_PASSWORD_RESET_COMPLETED,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_EMAIL_CHANGE_CONFIRMED,
    EVENT_EMAIL_VERIFICATION_COMPLETED,
    EVENT_CHAT_PROMPT,
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_CHAT_PROCESSING_ERROR,
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ROLE_CHANGED,
    EVENT_ADMIN_ACCESS_DENIED,
    EVENT_DATABASE_CONNECTION_FAILURE,
    EVENT_EMAIL_SENDING_FAILURE,
}

SUCCESS_EVENTS = {
    EVENT_LOGIN,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_ACCOUNT_REACTIVATED,
    EVENT_PASSWORD_RESET_COMPLETED,
    EVENT_EMAIL_CHANGE_CONFIRMED,
    EVENT_EMAIL_VERIFICATION_COMPLETED,
    EVENT_ACCESS_GRANTED,
}

FAILURE_EVENTS = {
    EVENT_LOGIN_FAILURE,
    EVENT_CHAT_PROCESSING_ERROR,
    EVENT_DATABASE_CONNECTION_FAILURE,
    EVENT_EMAIL_SENDING_FAILURE,
}

BLOCKED_EVENTS = {
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_ADMIN_ACCESS_DENIED,
}

INFO_EVENTS = {
    EVENT_LOGOUT,
    EVENT_PASSWORD_RESET_REQUESTED,
    EVENT_EMAIL_CHANGE_REQUESTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ROLE_CHANGED,
    EVENT_CHAT_PROMPT,
}

PROMPT_PREVIEW_MAX_LEN = 160
DETAIL_MAX_LEN = 2000


@dataclass(frozen=True)
class AuditEntry:
    id: int
    evento: str
    user_id: int | None
    user_email: str | None
    prompt_text: str | None
    detalhe: str | None
    criado_em: Any
    status: str | None = None
    source: str | None = None
    action: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(value: str | None, max_len: int = DETAIL_MAX_LEN) -> str | None:
    if value is None:
        return None
    return value[:max_len] if len(value) > max_len else value


def _safe_error_summary(exc: BaseException) -> str:
    message = str(getattr(exc, "orig", exc)).casefold()
    if "audit_log" in message and ("does not exist" in message or "no such table" in message):
        return "audit log table does not exist"

    try:
        from src.auth.user_service import safe_auth_exception_summary

        return safe_auth_exception_summary(exc)
    except Exception:
        return type(exc).__name__


def _sanitize_text(value: str | None, *, max_len: int = DETAIL_MAX_LEN) -> str | None:
    """Remove valores sensiveis antes de persistir/exibir auditoria."""
    if value is None:
        return None

    clean = str(value).strip()
    if not clean:
        return None

    clean = re.sub(
        r"(?i)\b(password|senha|token|api[_-]?key|secret|client_secret|smtp_password|db_password)\s*[:=]\s*[^\s,;]+",
        r"\1=[oculto]",
        clean,
    )
    clean = re.sub(
        r"(?i)(reset_password_token|verify_email_token|confirm_email_change_token)=([^&\s]+)",
        r"\1=[oculto]",
        clean,
    )
    clean = re.sub(
        r"(?i)\b(postgresql(?:\+\w+)?|mysql|mssql|oracle)://[^\s,;]+",
        "[db-url-oculta]",
        clean,
    )
    clean = re.sub(
        r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1[oculto]",
        clean,
    )
    return _truncate(clean, max_len=max_len)


def _sanitize_prompt_preview(value: str | None) -> str | None:
    return _sanitize_text(value, max_len=PROMPT_PREVIEW_MAX_LEN)


def _infer_status(evento: str) -> str:
    if evento in SUCCESS_EVENTS:
        return "success"
    if evento in FAILURE_EVENTS:
        return "failure"
    if evento in BLOCKED_EVENTS:
        return "blocked"
    if evento in INFO_EVENTS:
        return "info"
    return "info"


def _get_audit_columns(conn: Any, dialect: str) -> set[str]:
    try:
        if dialect == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(audit_log)")).mappings().all()
            return {str(row["name"]) for row in rows}

        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'audit_log'
                """
            )
        ).mappings().all()
        return {str(row["column_name"]) for row in rows}
    except SQLAlchemyError:
        return set()


def _add_column_if_missing(conn: Any, columns: set[str], column_name: str, definition: str) -> None:
    if column_name in columns:
        return
    conn.execute(text(f"ALTER TABLE audit_log ADD COLUMN {column_name} {definition}"))
    columns.add(column_name)


def _select_columns(conn: Any, dialect: str) -> str:
    columns = _get_audit_columns(conn, dialect)
    fields = [
        "id",
        "evento",
        "user_id",
        "user_email",
        "prompt_text",
        "detalhe",
        "criado_em",
        "status" if "status" in columns else "NULL AS status",
        "source" if "source" in columns else "NULL AS source",
        "action" if "action" in columns else "NULL AS action",
    ]
    return ", ".join(fields)


class AuditLogService:
    """Persiste e consulta eventos de auditoria na tabela audit_log."""

    def __init__(self, engine, initialize_schema: bool = True):
        self.engine = engine
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "AuditLogService":
        """Cria servico usando a mesma engine de autenticacao."""
        from src.auth.user_service import get_auth_engine

        return cls(get_auth_engine())

    def ensure_schema(self) -> None:
        """Cria a tabela audit_log se nao existir e evolui colunas seguras."""
        dialect = self.engine.dialect.name
        id_col = "id SERIAL PRIMARY KEY" if dialect == "postgresql" else "id INTEGER PRIMARY KEY AUTOINCREMENT"

        sql = f"""
            CREATE TABLE IF NOT EXISTS audit_log (
                {id_col},
                evento       TEXT        NOT NULL,
                user_id      INTEGER     NULL,
                user_email   TEXT        NULL,
                prompt_text  TEXT        NULL,
                detalhe      TEXT        NULL,
                status       TEXT        NULL,
                source       TEXT        NULL,
                action       TEXT        NULL,
                criado_em    TIMESTAMP   NOT NULL
            )
        """
        def operation() -> None:
            with self.engine.begin() as conn:
                conn.execute(text(sql))
                columns = _get_audit_columns(conn, dialect)
                _add_column_if_missing(conn, columns, "status", "TEXT NULL")
                _add_column_if_missing(conn, columns, "source", "TEXT NULL")
                _add_column_if_missing(conn, columns, "action", "TEXT NULL")
                if dialect == "postgresql":
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_evento ON audit_log (evento)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_status ON audit_log (status)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_log_criado_em ON audit_log (criado_em DESC)"))

        try:
            run_transient_db_operation("audit_log.ensure_schema", operation)
        except SQLAlchemyError as exc:
            logger.warning(
                "audit_log: falha ao criar schema | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    @traced_operation("audit.persist", {"audit.operation": "persist"})
    def log_event(
        self,
        evento: str,
        user_id: int | None = None,
        user_email: str | None = None,
        prompt_text: str | None = None,
        detalhe: str | None = None,
        status: str | None = None,
        source: str | None = None,
        action: str | None = None,
    ) -> None:
        """Registra um evento de auditoria. Falhas sao logadas mas nao propagadas."""
        if evento not in VALID_EVENTS:
            logger.warning("audit_log: evento desconhecido ignorado | evento=%s", evento)
            return

        safe_status = (status or _infer_status(evento)).strip().lower()
        if safe_status not in {"success", "failure", "blocked", "info"}:
            safe_status = _infer_status(evento)

        params = {
            "evento": evento,
            "user_id": user_id,
            "user_email": _sanitize_text(user_email, max_len=320),
            "prompt_text": _sanitize_prompt_preview(prompt_text),
            "detalhe": _sanitize_text(detalhe),
            "status": safe_status,
            "source": _sanitize_text(source, max_len=120),
            "action": _sanitize_text(action, max_len=120),
            "criado_em": _now(),
        }

        def operation() -> None:
            with self.engine.begin() as conn:
                dialect = self.engine.dialect.name
                columns = _get_audit_columns(conn, dialect)
                insert_columns = ["evento", "user_id", "user_email", "prompt_text", "detalhe", "criado_em"]
                for optional_column in ("status", "source", "action"):
                    if optional_column in columns:
                        insert_columns.append(optional_column)
                values = ", ".join(f":{column}" for column in insert_columns)
                conn.execute(
                    text(f"INSERT INTO audit_log ({', '.join(insert_columns)}) VALUES ({values})"),
                    params,
                )

        try:
            run_transient_db_operation("audit_log.log_event", operation)
        except SQLAlchemyError as exc:
            logger.warning(
                "audit_log: falha ao registrar evento | evento=%s | user_id=%s | causa=%s | tipo=%s",
                evento,
                user_id,
                _safe_error_summary(exc),
                type(exc).__name__,
            )
        except Exception as exc:
            logger.warning(
                "audit_log: falha inesperada ao registrar evento | evento=%s | user_id=%s | tipo=%s",
                evento,
                user_id,
                type(exc).__name__,
            )

    @traced_operation("audit.list", {"audit.operation": "list"})
    def get_recent_logs(self, limit: int = 200) -> list[AuditEntry]:
        """Retorna os eventos mais recentes em ordem decrescente."""
        def operation() -> list[Any]:
            with self.engine.connect() as conn:
                fields = _select_columns(conn, self.engine.dialect.name)
                rows = conn.execute(
                    text(
                        f"""
                        SELECT {fields}
                        FROM audit_log
                        ORDER BY criado_em DESC
                        LIMIT :limit
                        """
                    ),
                    {"limit": limit},
                ).mappings().all()
            return rows

        try:
            rows = run_transient_db_operation("audit_log.get_recent_logs", operation)
        except SQLAlchemyError as exc:
            logger.warning(
                "audit_log: falha ao buscar logs recentes | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            return []

        return [_row_to_entry(r) for r in rows]

    @traced_operation("audit.list", {"audit.operation": "list"})
    def get_logs_by_user(self, user_id: int, limit: int = 100) -> list[AuditEntry]:
        """Retorna eventos associados a um usuario especifico."""
        def operation() -> list[Any]:
            with self.engine.connect() as conn:
                fields = _select_columns(conn, self.engine.dialect.name)
                rows = conn.execute(
                    text(
                        f"""
                        SELECT {fields}
                        FROM audit_log
                        WHERE user_id = :user_id
                        ORDER BY criado_em DESC
                        LIMIT :limit
                        """
                    ),
                    {"user_id": user_id, "limit": limit},
                ).mappings().all()
            return rows

        try:
            rows = run_transient_db_operation("audit_log.get_logs_by_user", operation)
        except SQLAlchemyError as exc:
            logger.warning(
                "audit_log: falha ao buscar logs do usuario | user_id=%s | causa=%s | tipo=%s",
                user_id,
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            return []

        return [_row_to_entry(r) for r in rows]


def log_audit_event_safely(engine: Any, evento: str, **kwargs: Any) -> None:
    """Registra auditoria sem permitir que falhas quebrem o fluxo principal."""
    try:
        AuditLogService(engine, initialize_schema=False).log_event(evento, **kwargs)
    except Exception as exc:
        logger.warning(
            "audit_log: falha segura no helper | evento=%s | causa=%s | tipo=%s",
            evento,
            _safe_error_summary(exc),
            type(exc).__name__,
        )


def _row_to_entry(row: Any) -> AuditEntry:
    keys = set(row.keys()) if hasattr(row, "keys") else set()
    return AuditEntry(
        id=int(row["id"]),
        evento=row["evento"],
        user_id=row["user_id"],
        user_email=row["user_email"],
        prompt_text=row["prompt_text"],
        detalhe=row["detalhe"],
        criado_em=row["criado_em"],
        status=row["status"] if "status" in keys else None,
        source=row["source"] if "source" in keys else None,
        action=row["action"] if "action" in keys else None,
    )
