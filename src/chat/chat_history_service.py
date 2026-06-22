"""Persistencia de historico e auditoria basica do Chat IA."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError, SQLAlchemyError

from src.auth.user_service import get_auth_engine, safe_auth_exception_summary

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TITLE = "Conversa do Chat IA"
ALLOWED_ROLES = {"user", "assistant", "system"}
ALLOWED_STATUSES = {"ok", "blocked", "error", "fallback"}

_TOKEN_QUERY_RE = re.compile(r"\b(reset_password_token|verify_email_token)=([^\s&]+)", re.IGNORECASE)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(password|senha|api[_-]?key|token|secret|smtp[_-]?password)\s*[:=]\s*([^\s]+)",
    re.IGNORECASE,
)
_LONG_HEX_RE = re.compile(r"\b[a-f0-9]{48,}\b", re.IGNORECASE)


@dataclass(frozen=True)
class ChatSession:
    id: int
    user_id: int
    titulo: str
    criado_em: Any = None
    atualizado_em: Any = None


@dataclass(frozen=True)
class ChatMessage:
    id: int
    chat_session_id: int
    user_id: int
    role: str
    conteudo: str
    status: str
    criado_em: Any = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_error_summary(exc: BaseException) -> str:
    if isinstance(exc, SQLAlchemyError):
        return safe_auth_exception_summary(exc)
    return type(exc).__name__


def _get_table_columns(conn: Any, table_name: str) -> set[str]:
    if conn.dialect.name == "sqlite":
        return {
            row["name"]
            for row in conn.execute(text(f"PRAGMA table_info({table_name})")).mappings()
        }

    return {
        row["column_name"]
        for row in conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = :table_name
                  AND table_schema = current_schema()
                """
            ),
            {"table_name": table_name},
        ).mappings()
    }


def _add_column_if_missing(conn: Any, table_name: str, columns: set[str], column_name: str, definition: str) -> None:
    if column_name in columns:
        return

    if conn.dialect.name == "postgresql":
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {definition}"))
    else:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))

    columns.add(column_name)


def _active_record_condition(table_alias: str | None = None) -> str:
    prefix = f"{table_alias}." if table_alias else ""
    return f"{prefix}deletado IS NOT TRUE AND {prefix}deletado_em IS NULL"


def _clean_title(title: str | None) -> str:
    clean_title = " ".join(str(title or "").split())
    if not clean_title:
        return DEFAULT_CHAT_TITLE
    return clean_title[:90]


def redact_sensitive_content(content: str) -> str:
    clean_content = str(content or "")
    clean_content = _TOKEN_QUERY_RE.sub(r"\1=[REDACTED]", clean_content)
    clean_content = _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", clean_content)
    clean_content = _LONG_HEX_RE.sub("[REDACTED_HASH]", clean_content)
    return clean_content


def _row_to_session(row: Any) -> ChatSession:
    return ChatSession(
        id=int(row["id"]),
        user_id=int(row["user_id"]),
        titulo=row["titulo"],
        criado_em=row["criado_em"],
        atualizado_em=row["atualizado_em"],
    )


def _row_to_message(row: Any) -> ChatMessage:
    return ChatMessage(
        id=int(row["id"]),
        chat_session_id=int(row["chat_session_id"]),
        user_id=int(row["user_id"]),
        role=row["role"],
        conteudo=row["conteudo"],
        status=row["status"],
        criado_em=row["criado_em"],
    )


class ChatHistoryService:
    """Repositorio controlado para historico do Chat IA."""

    def __init__(self, engine, initialize_schema: bool = True):
        self.engine = engine
        if initialize_schema:
            self.ensure_schema()

    @classmethod
    def from_environment(cls) -> "ChatHistoryService":
        return cls(get_auth_engine())

    def ensure_schema(self) -> None:
        dialect = self.engine.dialect.name
        id_column = "id SERIAL PRIMARY KEY"
        if dialect == "sqlite":
            id_column = "id INTEGER PRIMARY KEY AUTOINCREMENT"

        create_sessions_sql = f"""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                {id_column},
                user_id INTEGER NOT NULL,
                titulo TEXT NOT NULL,
                criado_em TIMESTAMP NOT NULL,
                atualizado_em TIMESTAMP NOT NULL,
                deletado BOOLEAN NOT NULL DEFAULT false,
                deletado_em TIMESTAMP NULL
            )
        """
        create_messages_sql = f"""
            CREATE TABLE IF NOT EXISTS chat_messages (
                {id_column},
                chat_session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                conteudo TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                criado_em TIMESTAMP NOT NULL,
                deletado BOOLEAN NOT NULL DEFAULT false,
                deletado_em TIMESTAMP NULL
            )
        """

        try:
            with self.engine.begin() as conn:
                conn.execute(text(create_sessions_sql))
                conn.execute(text(create_messages_sql))

                session_columns = _get_table_columns(conn, "chat_sessions")
                _add_column_if_missing(conn, "chat_sessions", session_columns, "titulo", "TEXT NOT NULL DEFAULT 'Conversa do Chat IA'")
                _add_column_if_missing(conn, "chat_sessions", session_columns, "atualizado_em", "TIMESTAMP NULL")
                _add_column_if_missing(conn, "chat_sessions", session_columns, "deletado", "BOOLEAN NOT NULL DEFAULT false")
                _add_column_if_missing(conn, "chat_sessions", session_columns, "deletado_em", "TIMESTAMP NULL")
                conn.execute(text("UPDATE chat_sessions SET deletado = false WHERE deletado IS NULL"))
                conn.execute(text("UPDATE chat_sessions SET atualizado_em = criado_em WHERE atualizado_em IS NULL"))

                message_columns = _get_table_columns(conn, "chat_messages")
                _add_column_if_missing(conn, "chat_messages", message_columns, "status", "TEXT NOT NULL DEFAULT 'ok'")
                _add_column_if_missing(conn, "chat_messages", message_columns, "deletado", "BOOLEAN NOT NULL DEFAULT false")
                _add_column_if_missing(conn, "chat_messages", message_columns, "deletado_em", "TIMESTAMP NULL")
                conn.execute(text("UPDATE chat_messages SET deletado = false WHERE deletado IS NULL"))
                conn.execute(text("UPDATE chat_messages SET status = 'ok' WHERE status IS NULL"))

                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_chat_sessions_user_active
                        ON chat_sessions (user_id, deletado, deletado_em)
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE INDEX IF NOT EXISTS ix_chat_messages_session_user
                        ON chat_messages (chat_session_id, user_id, deletado, deletado_em)
                        """
                    )
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=ensure_schema | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def create_chat_session(self, user_id: int, title: str | None = None) -> ChatSession:
        clean_user_id = self._validate_user_id(user_id)
        now = _now()
        clean_title = _clean_title(title)

        try:
            with self.engine.begin() as conn:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO chat_sessions (
                            user_id,
                            titulo,
                            criado_em,
                            atualizado_em
                        )
                        VALUES (
                            :user_id,
                            :titulo,
                            :criado_em,
                            :atualizado_em
                        )
                        """
                    ),
                    {
                        "user_id": clean_user_id,
                        "titulo": clean_title,
                        "criado_em": now,
                        "atualizado_em": now,
                    },
                )
                session_id = getattr(result, "lastrowid", None)
                row = self._get_session_row_by_id(conn, session_id, clean_user_id) if session_id else None
                if row is None:
                    row = conn.execute(
                        text(
                            f"""
                            SELECT id, user_id, titulo, criado_em, atualizado_em
                            FROM chat_sessions
                            WHERE user_id = :user_id
                              AND {_active_record_condition()}
                            ORDER BY id DESC
                            LIMIT 1
                            """
                        ),
                        {"user_id": clean_user_id},
                    ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=create_session | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return _row_to_session(row)

    def get_or_create_active_chat_session(self, user_id: int, title: str | None = None) -> ChatSession:
        clean_user_id = self._validate_user_id(user_id)
        try:
            with self.engine.connect() as conn:
                row = conn.execute(
                    text(
                        f"""
                        SELECT id, user_id, titulo, criado_em, atualizado_em
                        FROM chat_sessions
                        WHERE user_id = :user_id
                          AND {_active_record_condition()}
                        ORDER BY atualizado_em DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"user_id": clean_user_id},
                ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=get_active_session | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return _row_to_session(row) if row else self.create_chat_session(clean_user_id, title)

    def get_chat_session(self, chat_session_id: int, user_id: int) -> ChatSession | None:
        clean_user_id = self._validate_user_id(user_id)
        clean_session_id = self._validate_id(chat_session_id, "chat_session_id")
        try:
            with self.engine.connect() as conn:
                row = self._get_session_row_by_id(conn, clean_session_id, clean_user_id)
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=get_session | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return _row_to_session(row) if row else None

    def add_chat_message(
        self,
        chat_session_id: int,
        user_id: int,
        role: str,
        content: str,
        status: str = "ok",
    ) -> ChatMessage:
        clean_user_id = self._validate_user_id(user_id)
        clean_session_id = self._validate_id(chat_session_id, "chat_session_id")
        clean_role = self._validate_role(role)
        clean_status = self._validate_status(status)
        clean_content = redact_sensitive_content(content)
        now = _now()

        try:
            with self.engine.begin() as conn:
                session = self._get_session_row_by_id(conn, clean_session_id, clean_user_id)
                if session is None:
                    raise ValueError("chat session not found for user")

                result = conn.execute(
                    text(
                        """
                        INSERT INTO chat_messages (
                            chat_session_id,
                            user_id,
                            role,
                            conteudo,
                            status,
                            criado_em
                        )
                        VALUES (
                            :chat_session_id,
                            :user_id,
                            :role,
                            :conteudo,
                            :status,
                            :criado_em
                        )
                        """
                    ),
                    {
                        "chat_session_id": clean_session_id,
                        "user_id": clean_user_id,
                        "role": clean_role,
                        "conteudo": clean_content,
                        "status": clean_status,
                        "criado_em": now,
                    },
                )
                conn.execute(
                    text(
                        """
                        UPDATE chat_sessions
                        SET atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND user_id = :user_id
                        """
                    ),
                    {"id": clean_session_id, "user_id": clean_user_id, "atualizado_em": now},
                )
                message_id = getattr(result, "lastrowid", None)
                row = self._get_message_row_by_id(conn, message_id, clean_user_id) if message_id else None
                if row is None:
                    row = conn.execute(
                        text(
                            f"""
                            SELECT id, chat_session_id, user_id, role, conteudo, status, criado_em
                            FROM chat_messages
                            WHERE chat_session_id = :chat_session_id
                              AND user_id = :user_id
                              AND {_active_record_condition()}
                            ORDER BY id DESC
                            LIMIT 1
                            """
                        ),
                        {"chat_session_id": clean_session_id, "user_id": clean_user_id},
                    ).mappings().first()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=add_message | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return _row_to_message(row)

    def list_user_chat_sessions(self, user_id: int) -> list[ChatSession]:
        clean_user_id = self._validate_user_id(user_id)
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text(
                        f"""
                        SELECT id, user_id, titulo, criado_em, atualizado_em
                        FROM chat_sessions
                        WHERE user_id = :user_id
                          AND {_active_record_condition()}
                        ORDER BY atualizado_em DESC, id DESC
                        """
                    ),
                    {"user_id": clean_user_id},
                ).mappings().all()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=list_sessions | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return [_row_to_session(row) for row in rows]

    def list_chat_messages(self, chat_session_id: int, user_id: int) -> list[ChatMessage]:
        clean_user_id = self._validate_user_id(user_id)
        clean_session_id = self._validate_id(chat_session_id, "chat_session_id")
        try:
            with self.engine.connect() as conn:
                session = self._get_session_row_by_id(conn, clean_session_id, clean_user_id)
                if session is None:
                    return []
                rows = conn.execute(
                    text(
                        f"""
                        SELECT id, chat_session_id, user_id, role, conteudo, status, criado_em
                        FROM chat_messages
                        WHERE chat_session_id = :chat_session_id
                          AND user_id = :user_id
                          AND {_active_record_condition()}
                        ORDER BY criado_em ASC, id ASC
                        """
                    ),
                    {"chat_session_id": clean_session_id, "user_id": clean_user_id},
                ).mappings().all()
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=list_messages | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

        return [_row_to_message(row) for row in rows]

    def soft_delete_chat_session(self, chat_session_id: int, user_id: int) -> None:
        clean_user_id = self._validate_user_id(user_id)
        clean_session_id = self._validate_id(chat_session_id, "chat_session_id")
        now = _now()
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        f"""
                        UPDATE chat_sessions
                        SET deletado = :deletado,
                            deletado_em = :deletado_em,
                            atualizado_em = :atualizado_em
                        WHERE id = :id
                          AND user_id = :user_id
                          AND {_active_record_condition()}
                        """
                    ),
                    {
                        "id": clean_session_id,
                        "user_id": clean_user_id,
                        "deletado": True,
                        "deletado_em": now,
                        "atualizado_em": now,
                    },
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=soft_delete_session | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def soft_delete_chat_message(self, message_id: int, user_id: int) -> None:
        clean_user_id = self._validate_user_id(user_id)
        clean_message_id = self._validate_id(message_id, "message_id")
        now = _now()
        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        f"""
                        UPDATE chat_messages
                        SET deletado = :deletado,
                            deletado_em = :deletado_em
                        WHERE id = :id
                          AND user_id = :user_id
                          AND {_active_record_condition()}
                        """
                    ),
                    {
                        "id": clean_message_id,
                        "user_id": clean_user_id,
                        "deletado": True,
                        "deletado_em": now,
                    },
                )
        except SQLAlchemyError as exc:
            logger.warning(
                "Erro seguro historico_chat | acao=soft_delete_message | causa=%s | tipo=%s",
                _safe_error_summary(exc),
                type(exc).__name__,
            )
            raise

    def _get_session_row_by_id(self, conn: Any, chat_session_id: int | None, user_id: int) -> Any | None:
        if not chat_session_id:
            return None
        return conn.execute(
            text(
                f"""
                SELECT id, user_id, titulo, criado_em, atualizado_em
                FROM chat_sessions
                WHERE id = :id
                  AND user_id = :user_id
                  AND {_active_record_condition()}
                LIMIT 1
                """
            ),
            {"id": chat_session_id, "user_id": user_id},
        ).mappings().first()

    def _get_message_row_by_id(self, conn: Any, message_id: int | None, user_id: int) -> Any | None:
        if not message_id:
            return None
        return conn.execute(
            text(
                f"""
                SELECT id, chat_session_id, user_id, role, conteudo, status, criado_em
                FROM chat_messages
                WHERE id = :id
                  AND user_id = :user_id
                  AND {_active_record_condition()}
                LIMIT 1
                """
            ),
            {"id": message_id, "user_id": user_id},
        ).mappings().first()

    @staticmethod
    def _validate_user_id(user_id: int) -> int:
        return ChatHistoryService._validate_id(user_id, "user_id")

    @staticmethod
    def _validate_id(value: int, field_name: str) -> int:
        try:
            clean_value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{field_name} invalido") from None
        if clean_value <= 0:
            raise ValueError(f"{field_name} invalido")
        return clean_value

    @staticmethod
    def _validate_role(role: str) -> str:
        clean_role = (role or "").strip().lower()
        if clean_role not in ALLOWED_ROLES:
            raise ValueError("role invalido")
        return clean_role

    @staticmethod
    def _validate_status(status: str) -> str:
        clean_status = (status or "ok").strip().lower()
        if clean_status not in ALLOWED_STATUSES:
            clean_status = "ok"
        return clean_status
