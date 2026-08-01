"""Raw psycopg2 queries against usuarios. No business logic, no password hashing here.

Soft-delete uses the actual production columns (deletado / deleted_at / deletado_em) —
NOT an `ativo` flag. See docs/claude-migration.md for why this deviates from the
prompt's schema sketch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

ACTIVE_CONDITION = "deletado IS NOT TRUE AND deleted_at IS NULL AND deletado_em IS NULL"

USER_COLUMNS = """
    id, nome, email, senha_hash, role, criado_em, atualizado_em, ultimo_login_em,
    COALESCE(can_view_audit, false) AS can_view_audit,
    COALESCE(email_verificado, false) AS email_verificado,
    google_sub, auth_provider
"""


def get_user_by_email(conn: Any, email: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {USER_COLUMNS}
            FROM usuarios
            WHERE lower(email) = %(email)s
              AND {ACTIVE_CONDITION}
            LIMIT 1
            """,
            {"email": email},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_user_by_id(conn: Any, user_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {USER_COLUMNS}
            FROM usuarios
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            LIMIT 1
            """,
            {"id": user_id},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def active_email_exists(conn: Any, email: str, *, exclude_user_id: int | None = None) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id
            FROM usuarios
            WHERE lower(email) = %(email)s
              AND {ACTIVE_CONDITION}
              AND (%(exclude_user_id)s IS NULL OR id <> %(exclude_user_id)s)
            LIMIT 1
            """,
            {"email": email, "exclude_user_id": exclude_user_id},
        )
        return cur.fetchone() is not None


def create_user(conn: Any, nome: str, email: str, senha_hash: str, role: str) -> int:
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO usuarios (nome, email, senha_hash, role, criado_em, atualizado_em)
            VALUES (%(nome)s, %(email)s, %(senha_hash)s, %(role)s, %(criado_em)s, %(atualizado_em)s)
            RETURNING id
            """,
            {
                "nome": nome,
                "email": email,
                "senha_hash": senha_hash,
                "role": role,
                "criado_em": now,
                "atualizado_em": now,
            },
        )
        user_id = cur.fetchone()["id"]
    conn.commit()
    return user_id


def update_last_login(conn: Any, user_id: int) -> None:
    now = datetime.utcnow()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE usuarios
            SET ultimo_login_em = %(now)s, atualizado_em = %(now)s
            WHERE id = %(id)s
            """,
            {"id": user_id, "now": now},
        )
    conn.commit()


def update_user_name(conn: Any, user_id: int, nome: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET nome = %(nome)s, atualizado_em = %(now)s
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "nome": nome, "now": datetime.utcnow()},
        )
    conn.commit()


def update_user_email(conn: Any, user_id: int, email: str) -> None:
    """Updates email and resets email_verificado, mirroring src/auth/user_service.py:update_email."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET email = %(email)s,
                atualizado_em = %(now)s,
                email_verificado = false,
                email_verificado_em = NULL
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "email": email, "now": datetime.utcnow()},
        )
    conn.commit()


def update_user_password(conn: Any, user_id: int, senha_hash: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE usuarios
            SET senha_hash = %(senha_hash)s, atualizado_em = %(now)s
            WHERE id = %(id)s
            """,
            {"id": user_id, "senha_hash": senha_hash, "now": datetime.utcnow()},
        )
    conn.commit()


def update_active_user_password(conn: Any, user_id: int, senha_hash: str) -> int:
    """Used by password-reset completion; returns rowcount (0 if the user is no longer active)."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE usuarios
            SET senha_hash = %(senha_hash)s, atualizado_em = %(now)s
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            """,
            {"id": user_id, "senha_hash": senha_hash, "now": datetime.utcnow()},
        )
        rowcount = cur.rowcount
    conn.commit()
    return rowcount


def get_password_hash(conn: Any, user_id: int) -> str | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT senha_hash
            FROM usuarios
            WHERE id = %(id)s
              AND {ACTIVE_CONDITION}
            LIMIT 1
            """,
            {"id": user_id},
        )
        row = cur.fetchone()
        return row["senha_hash"] if row else None


def create_password_reset_token(conn: Any, user_id: int, token_hash: str, criado_em: datetime, expira_em: datetime) -> None:
    """password_reset_tokens is created/migrated by the legacy app's own ensure_schema();
    this module only reads/writes rows, it never creates the table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, criado_em, expira_em)
            VALUES (%(user_id)s, %(token_hash)s, %(criado_em)s, %(expira_em)s)
            """,
            {"user_id": user_id, "token_hash": token_hash, "criado_em": criado_em, "expira_em": expira_em},
        )
    conn.commit()


def get_password_reset_token_by_hash(conn: Any, token_hash: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, user_id, expira_em, usado_em
            FROM password_reset_tokens
            WHERE token_hash = %(token_hash)s
            LIMIT 1
            """,
            {"token_hash": token_hash},
        )
        row = cur.fetchone()
        return dict(row) if row else None


def mark_password_reset_token_used(conn: Any, token_id: int, usado_em: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE password_reset_tokens SET usado_em = %(usado_em)s WHERE id = %(id)s",
            {"id": token_id, "usado_em": usado_em},
        )
    conn.commit()


def deactivate_own_account(conn: Any, user_id: int) -> None:
    """Self-service deactivation (profile page). Never runs DELETE."""
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
