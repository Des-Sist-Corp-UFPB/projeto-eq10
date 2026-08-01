"""psycopg2 connection helper for the auth database. Raw psycopg2 only, no ORM."""

from __future__ import annotations

import os

import psycopg2
import psycopg2.extras


def _is_local_host(host: str) -> bool:
    return host.strip().lower() in {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def _sslmode_for(host: str) -> str:
    return (
        os.environ.get("AUTH_DB_SSLMODE")
        or ("disable" if _is_local_host(host) else "require")
    )


def get_auth_connection() -> psycopg2.extensions.connection:
    """Open a new connection to the auth database (users, audit_log, chat_*).

    Caller owns the connection lifecycle (commit/rollback/close).
    """
    database_url = os.environ.get("AUTH_DATABASE_URL", "").strip()
    if database_url:
        return psycopg2.connect(database_url, cursor_factory=psycopg2.extras.RealDictCursor)

    host = os.environ.get("AUTH_DB_HOST", "").strip()
    return psycopg2.connect(
        host=host,
        port=os.environ.get("AUTH_DB_PORT", "5432"),
        dbname=os.environ.get("AUTH_DB_NAME", ""),
        user=os.environ.get("AUTH_DB_USER", ""),
        password=os.environ.get("AUTH_DB_PASSWORD", ""),
        sslmode=_sslmode_for(host),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
