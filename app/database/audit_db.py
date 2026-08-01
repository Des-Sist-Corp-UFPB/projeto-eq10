"""Raw psycopg2 queries against audit_log. No business logic, no sanitization here."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def insert_audit_log(
    conn: Any,
    evento: str,
    user_id: int | None,
    user_email: str | None,
    prompt_text: str | None,
    detalhe: str | None,
    status: str | None,
    source: str | None,
    action: str | None,
    criado_em: datetime,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_log (
                evento, user_id, user_email, prompt_text, detalhe, status, source, action, criado_em
            ) VALUES (%(evento)s, %(user_id)s, %(user_email)s, %(prompt_text)s, %(detalhe)s,
                      %(status)s, %(source)s, %(action)s, %(criado_em)s)
            """,
            {
                "evento": evento,
                "user_id": user_id,
                "user_email": user_email,
                "prompt_text": prompt_text,
                "detalhe": detalhe,
                "status": status,
                "source": source,
                "action": action,
                "criado_em": criado_em,
            },
        )
    conn.commit()


def get_recent_audit_logs(conn: Any, limit: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evento, user_id, user_email, prompt_text, detalhe, status, source, action, criado_em
            FROM audit_log
            ORDER BY criado_em DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]


def get_audit_logs_by_user(conn: Any, user_id: int, limit: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, evento, user_id, user_email, prompt_text, detalhe, status, source, action, criado_em
            FROM audit_log
            WHERE user_id = %(user_id)s
            ORDER BY criado_em DESC
            LIMIT %(limit)s
            """,
            {"user_id": user_id, "limit": limit},
        )
        return [dict(row) for row in cur.fetchall()]
