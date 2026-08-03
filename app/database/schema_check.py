"""Non-fatal startup diagnostics for the auth database. Never blocks app startup —
mirrors src/diagnostics/health_service.py's philosophy of degrading loudly, not crashing.

This exists specifically to turn "mystery 500 on first login" into an actionable startup
log line, since app/database/auth_db.py assumes the legacy app's ensure_schema() has
already migrated the real Postgres and this module never runs DDL for `usuarios` itself.
"""

from __future__ import annotations

import logging
from typing import Any

from app.database.auth_db import EXPECTED_USER_COLUMNS

logger = logging.getLogger(__name__)


def check_usuarios_columns(conn: Any) -> list[str]:
    """Returns the subset of EXPECTED_USER_COLUMNS missing from the real usuarios table."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'usuarios'
              AND table_schema = current_schema()
            """
        )
        existing = {row["column_name"] for row in cur.fetchall()}

    return [column for column in EXPECTED_USER_COLUMNS if column not in existing]


def ensure_password_reset_tokens_table(conn: Any) -> None:
    """Non-destructive CREATE TABLE IF NOT EXISTS — same shape as the legacy
    PasswordResetService.ensure_schema(), for environments where that service hasn't run
    against this database yet. Never drops or alters an existing table.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                criado_em TIMESTAMP NOT NULL,
                expira_em TIMESTAMP NOT NULL,
                usado_em TIMESTAMP NULL
            )
            """
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_password_reset_tokens_hash ON password_reset_tokens (token_hash)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS ix_password_reset_tokens_user ON password_reset_tokens (user_id)"
        )
    conn.commit()


def run_startup_checks() -> None:
    """Best-effort — logs a clear warning on schema drift or a dead DB, never raises."""
    from app.database.connection import get_auth_connection

    try:
        conn = get_auth_connection()
    except Exception as exc:
        logger.warning(
            "Startup schema check skipped | code=auth_db_unreachable | tipo=%s",
            type(exc).__name__,
        )
        return

    try:
        missing = check_usuarios_columns(conn)
        if missing:
            logger.error(
                "Startup schema check FAILED | table=usuarios | missing_columns=%s | "
                "login/register/profile will 500 until these exist. Run the legacy app's "
                "UserService.ensure_schema() against this database, or add the columns manually.",
                ",".join(missing),
            )
        else:
            logger.info("Startup schema check OK | table=usuarios | all expected columns present")

        ensure_password_reset_tokens_table(conn)
    except Exception as exc:
        logger.warning(
            "Startup schema check failed unexpectedly | tipo=%s | login will still be attempted",
            type(exc).__name__,
        )
    finally:
        conn.close()
