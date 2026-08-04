"""app/database/connection.py + app/database/schema_check.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.database import schema_check
from app.database.auth_db import EXPECTED_USER_COLUMNS
from app.database.connection import _is_local_host, _sslmode_for, get_auth_connection


# ── connection.py ───────────────────────────────────────────────────────────────


def test_is_local_host():
    assert _is_local_host("localhost") is True
    assert _is_local_host("127.0.0.1") is True
    assert _is_local_host("postgres") is True
    assert _is_local_host("db") is True
    assert _is_local_host("real-prod-host.example.com") is False


def test_sslmode_for_local_defaults_disable(monkeypatch):
    monkeypatch.delenv("AUTH_DB_SSLMODE", raising=False)
    assert _sslmode_for("localhost") == "disable"


def test_sslmode_for_remote_defaults_require(monkeypatch):
    monkeypatch.delenv("AUTH_DB_SSLMODE", raising=False)
    assert _sslmode_for("prod.example.com") == "require"


def test_sslmode_for_respects_explicit_env(monkeypatch):
    monkeypatch.setenv("AUTH_DB_SSLMODE", "prefer")
    assert _sslmode_for("prod.example.com") == "prefer"


def test_get_auth_connection_uses_database_url_when_set(monkeypatch):
    monkeypatch.setenv("AUTH_DATABASE_URL", "postgresql://user:pw@host:5432/db")
    with patch("psycopg2.connect") as fake_connect:
        get_auth_connection()
    args, kwargs = fake_connect.call_args
    assert args[0] == "postgresql://user:pw@host:5432/db"


def test_get_auth_connection_uses_discrete_vars_when_no_url(monkeypatch):
    monkeypatch.delenv("AUTH_DATABASE_URL", raising=False)
    monkeypatch.setenv("AUTH_DB_HOST", "myhost")
    monkeypatch.setenv("AUTH_DB_PORT", "5433")
    monkeypatch.setenv("AUTH_DB_NAME", "mydb")
    monkeypatch.setenv("AUTH_DB_USER", "myuser")
    monkeypatch.setenv("AUTH_DB_PASSWORD", "mypass")
    with patch("psycopg2.connect") as fake_connect:
        get_auth_connection()
    _, kwargs = fake_connect.call_args
    assert kwargs["host"] == "myhost"
    assert kwargs["port"] == "5433"
    assert kwargs["dbname"] == "mydb"


# ── schema_check.py ─────────────────────────────────────────────────────────────


def _fake_conn_with_columns(columns):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchall.return_value = [{"column_name": c} for c in columns]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn


def test_check_usuarios_columns_reports_none_missing_when_all_present():
    conn = _fake_conn_with_columns(EXPECTED_USER_COLUMNS)
    assert schema_check.check_usuarios_columns(conn) == []


def test_check_usuarios_columns_reports_missing_ones():
    conn = _fake_conn_with_columns(["id", "nome", "email"])
    missing = schema_check.check_usuarios_columns(conn)
    assert "senha_hash" in missing
    assert "deletado" in missing


def test_ensure_password_reset_tokens_table_uses_advisory_lock():
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cursor

    schema_check.ensure_password_reset_tokens_table(conn)

    executed_sql = " ".join(str(call.args[0]) for call in cursor.execute.call_args_list)
    assert "pg_advisory_lock" in executed_sql
    assert "pg_advisory_unlock" in executed_sql
    assert "CREATE TABLE IF NOT EXISTS password_reset_tokens" in executed_sql
    assert conn.commit.call_count == 2


def test_run_startup_checks_skips_gracefully_when_db_unreachable():
    with patch("app.database.connection.get_auth_connection", side_effect=RuntimeError("no route")):
        schema_check.run_startup_checks()  # must not raise


def test_run_startup_checks_logs_missing_columns(caplog):
    conn = _fake_conn_with_columns(["id"])
    with patch("app.database.connection.get_auth_connection", return_value=conn), \
         patch("app.database.schema_check.ensure_password_reset_tokens_table"):
        schema_check.run_startup_checks()
    conn.close.assert_called_once()


def test_run_startup_checks_handles_unexpected_exception():
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("boom")
    with patch("app.database.connection.get_auth_connection", return_value=conn):
        schema_check.run_startup_checks()  # must not raise
    conn.close.assert_called_once()
