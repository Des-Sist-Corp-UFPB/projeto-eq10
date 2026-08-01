"""Raw psycopg2 queries against chat_sessions / chat_messages. No business logic here.

Neither table is created by this module — both are migrated by the legacy app's
ChatHistoryService.ensure_schema(), which keeps running since app_ai_chat.py is untouched.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

ACTIVE_CONDITION = "deletado IS NOT TRUE AND deletado_em IS NULL"


def get_active_chat_session(conn: Any, user_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, user_id, titulo, criado_em, atualizado_em
            FROM chat_sessions
            WHERE user_id = %(user_id)s
              AND {ACTIVE_CONDITION}
            ORDER BY atualizado_em DESC, id DESC
            LIMIT 1
            """,
            {"user_id": user_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def create_chat_session(conn: Any, user_id: int, titulo: str) -> int:
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_sessions (user_id, titulo, criado_em, atualizado_em)
            VALUES (%(user_id)s, %(titulo)s, %(criado_em)s, %(atualizado_em)s)
            RETURNING id
            """,
            {"user_id": user_id, "titulo": titulo, "criado_em": now, "atualizado_em": now},
        )
        session_id = cur.fetchone()["id"]
    conn.commit()
    return session_id


def get_chat_session(conn: Any, chat_session_id: int, user_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, user_id, titulo, criado_em, atualizado_em
            FROM chat_sessions
            WHERE id = %(id)s
              AND user_id = %(user_id)s
              AND {ACTIVE_CONDITION}
            LIMIT 1
            """,
            {"id": chat_session_id, "user_id": user_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def touch_chat_session(conn: Any, chat_session_id: int, user_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE chat_sessions
            SET atualizado_em = %(now)s
            WHERE id = %(id)s
              AND user_id = %(user_id)s
            """,
            {"id": chat_session_id, "user_id": user_id, "now": datetime.utcnow()},
        )
    conn.commit()


def add_chat_message(conn: Any, session_id: int, user_id: int, role: str, conteudo: str, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO chat_messages (chat_session_id, user_id, role, conteudo, status, criado_em)
            VALUES (%(chat_session_id)s, %(user_id)s, %(role)s, %(conteudo)s, %(status)s, %(criado_em)s)
            """,
            {
                "chat_session_id": session_id,
                "user_id": user_id,
                "role": role,
                "conteudo": conteudo,
                "status": status,
                "criado_em": datetime.utcnow(),
            },
        )
    conn.commit()
    touch_chat_session(conn, session_id, user_id)


def get_chat_messages(conn: Any, session_id: int, user_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, chat_session_id, user_id, role, conteudo, status, criado_em
            FROM chat_messages
            WHERE chat_session_id = %(session_id)s
              AND user_id = %(user_id)s
              AND {ACTIVE_CONDITION}
            ORDER BY criado_em ASC, id ASC
            """,
            {"session_id": session_id, "user_id": user_id},
        )
        return [dict(row) for row in cur.fetchall()]
