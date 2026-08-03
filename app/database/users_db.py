"""Raw psycopg2 queries for admin user management. No business logic here.

Never runs DELETE — soft_delete_user() flips deletado/deleted_at/deletado_em, same
columns as app/database/auth_db.py's self-service deactivate_own_account().
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

ACTIVE_CONDITION = "deletado IS NOT TRUE AND deleted_at IS NULL AND deletado_em IS NULL"


def get_all_users(conn: Any) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, nome, email, role, criado_em, atualizado_em, ultimo_login_em,
                   COALESCE(can_view_audit, false) AS can_view_audit
            FROM usuarios
            WHERE {ACTIVE_CONDITION}
            ORDER BY criado_em DESC
            """
        )
        return [dict(row) for row in cur.fetchall()]


def update_user_role(conn: Any, user_id: int, new_role: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET role = %(role)s, atualizado_em = %(now)s
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "role": new_role, "now": datetime.utcnow()},
        )
    conn.commit()


def update_audit_access(conn: Any, user_id: int, can_view_audit: bool) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET can_view_audit = %(val)s, atualizado_em = %(now)s
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "val": can_view_audit, "now": datetime.utcnow()},
        )
    conn.commit()


def soft_delete_user(conn: Any, user_id: int) -> None:
    """Admin-initiated deactivation. NEVER runs DELETE."""
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET deletado = true, deleted_at = %(now)s, deletado_em = %(now)s, atualizado_em = %(now)s
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "now": now},
        )
    conn.commit()
