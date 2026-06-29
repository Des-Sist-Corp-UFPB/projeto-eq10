"""Servico de auditoria: persiste eventos de seguranca e uso do sistema."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Tipos de evento suportados
# ──────────────────────────────────────────────
EVENT_LOGIN = "login"
EVENT_ACCOUNT_CREATED = "account_created"
EVENT_ACCOUNT_DELETED = "account_deleted"
EVENT_CHAT_PROMPT = "chat_prompt"
EVENT_PROMPT_GUARD_BLOCK = "prompt_guard_block"
EVENT_ACCESS_GRANTED = "access_granted"
EVENT_ACCESS_REVOKED = "access_revoked"
EVENT_ROLE_CHANGED = "role_changed"

VALID_EVENTS = {
    EVENT_LOGIN,
    EVENT_ACCOUNT_CREATED,
    EVENT_ACCOUNT_DELETED,
    EVENT_CHAT_PROMPT,
    EVENT_PROMPT_GUARD_BLOCK,
    EVENT_ACCESS_GRANTED,
    EVENT_ACCESS_REVOKED,
    EVENT_ROLE_CHANGED,
}


@dataclass(frozen=True)
class AuditEntry:
    id: int
    evento: str
    user_id: int | None
    user_email: str | None
    prompt_text: str | None
    detalhe: str | None
    criado_em: Any


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _truncate(text: str | None, max_len: int = 2000) -> str | None:
    """Trunca texto longo para evitar entradas gigantes no banco."""
    if text is None:
        return None
    return text[:max_len] if len(text) > max_len else text


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
        """Cria a tabela audit_log se nao existir."""
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
                criado_em    TIMESTAMP   NOT NULL
            )
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text(sql))
                # Indice para busca por usuario e evento
                if dialect == "postgresql":
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_audit_log_user_id ON audit_log (user_id)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_audit_log_evento ON audit_log (evento)"
                    ))
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_audit_log_criado_em ON audit_log (criado_em DESC)"
                    ))
        except SQLAlchemyError:
            logger.exception("Erro ao criar tabela audit_log")
            raise

    def log_event(
        self,
        evento: str,
        user_id: int | None = None,
        user_email: str | None = None,
        prompt_text: str | None = None,
        detalhe: str | None = None,
    ) -> None:
        """Registra um evento de auditoria. Falhas sao logadas mas nao propagadas."""
        if evento not in VALID_EVENTS:
            logger.warning("audit_log: evento desconhecido ignorado | evento=%s", evento)
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO audit_log
                            (evento, user_id, user_email, prompt_text, detalhe, criado_em)
                        VALUES
                            (:evento, :user_id, :user_email, :prompt_text, :detalhe, :criado_em)
                    """),
                    {
                        "evento": evento,
                        "user_id": user_id,
                        "user_email": user_email,
                        "prompt_text": _truncate(prompt_text),
                        "detalhe": _truncate(detalhe),
                        "criado_em": _now(),
                    },
                )
        except SQLAlchemyError:
            logger.exception(
                "audit_log: falha ao registrar evento | evento=%s | user_id=%s",
                evento,
                user_id,
            )

    def get_recent_logs(self, limit: int = 200) -> list[AuditEntry]:
        """Retorna os eventos mais recentes em ordem decrescente."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, evento, user_id, user_email, prompt_text, detalhe, criado_em
                        FROM audit_log
                        ORDER BY criado_em DESC
                        LIMIT :limit
                    """),
                    {"limit": limit},
                ).mappings().all()
        except SQLAlchemyError:
            logger.exception("audit_log: falha ao buscar logs recentes")
            return []

        return [_row_to_entry(r) for r in rows]

    def get_logs_by_user(self, user_id: int, limit: int = 100) -> list[AuditEntry]:
        """Retorna eventos associados a um usuario especifico."""
        try:
            with self.engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT id, evento, user_id, user_email, prompt_text, detalhe, criado_em
                        FROM audit_log
                        WHERE user_id = :user_id
                        ORDER BY criado_em DESC
                        LIMIT :limit
                    """),
                    {"user_id": user_id, "limit": limit},
                ).mappings().all()
        except SQLAlchemyError:
            logger.exception("audit_log: falha ao buscar logs do usuario | user_id=%s", user_id)
            return []

        return [_row_to_entry(r) for r in rows]


def _row_to_entry(row: Any) -> AuditEntry:
    return AuditEntry(
        id=int(row["id"]),
        evento=row["evento"],
        user_id=row["user_id"],
        user_email=row["user_email"],
        prompt_text=row["prompt_text"],
        detalhe=row["detalhe"],
        criado_em=row["criado_em"],
    )
