"""app/database/*.py — raw SQL wrappers exercised against a MagicMock cursor/connection,
no live Postgres. Verifies each function executes and shapes results correctly, not the
literal SQL text (that needs a real Postgres — see docs/claude-migration.md's testing notes).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.database import audit_db, auth_db, chat_db, users_db


def _fake_conn(fetchone=None, fetchall=None, rowcount=1):
    cursor = MagicMock()
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    cursor.fetchone.return_value = fetchone
    cursor.fetchall.return_value = fetchall or []
    cursor.rowcount = rowcount

    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


# ── auth_db.py ──────────────────────────────────────────────────────────────────


def test_get_user_by_email_found():
    conn, cursor = _fake_conn(fetchone={"id": 1, "email": "a@b.com"})
    result = auth_db.get_user_by_email(conn, "a@b.com")
    assert result == {"id": 1, "email": "a@b.com"}
    cursor.execute.assert_called_once()


def test_get_user_by_email_not_found():
    conn, _ = _fake_conn(fetchone=None)
    assert auth_db.get_user_by_email(conn, "nobody@example.com") is None


def test_get_user_by_id():
    conn, _ = _fake_conn(fetchone={"id": 5})
    assert auth_db.get_user_by_id(conn, 5) == {"id": 5}


def test_active_email_exists_true_and_false():
    conn, _ = _fake_conn(fetchone={"id": 1})
    assert auth_db.active_email_exists(conn, "a@b.com") is True

    conn2, _ = _fake_conn(fetchone=None)
    assert auth_db.active_email_exists(conn2, "a@b.com") is False


def test_create_user_returns_id_and_commits():
    conn, cursor = _fake_conn(fetchone={"id": 42})
    user_id = auth_db.create_user(conn, "Ana", "a@b.com", "hash", "user")
    assert user_id == 42
    conn.commit.assert_called_once()


def test_update_last_login_commits():
    conn, cursor = _fake_conn()
    auth_db.update_last_login(conn, 1)
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_update_user_name_and_email():
    conn, _ = _fake_conn()
    auth_db.update_user_name(conn, 1, "Nome Novo")
    auth_db.update_user_email(conn, 1, "novo@example.com")
    assert conn.commit.call_count == 2


def test_update_user_password_and_active_variant():
    conn, cursor = _fake_conn(rowcount=1)
    auth_db.update_user_password(conn, 1, "hash2")
    rowcount = auth_db.update_active_user_password(conn, 1, "hash3")
    assert rowcount == 1


def test_get_password_hash_present_and_absent():
    conn, _ = _fake_conn(fetchone={"senha_hash": "abc"})
    assert auth_db.get_password_hash(conn, 1) == "abc"

    conn2, _ = _fake_conn(fetchone=None)
    assert auth_db.get_password_hash(conn2, 1) is None


def test_password_reset_token_lifecycle():
    from datetime import datetime

    conn, _ = _fake_conn()
    auth_db.create_password_reset_token(conn, 1, "hash", datetime.utcnow(), datetime.utcnow())

    conn2, _ = _fake_conn(fetchone={"id": 1, "user_id": 1, "expira_em": None, "usado_em": None})
    row = auth_db.get_password_reset_token_by_hash(conn2, "hash")
    assert row["id"] == 1

    conn3, _ = _fake_conn()
    auth_db.mark_password_reset_token_used(conn3, 1, datetime.utcnow())
    conn3.commit.assert_called_once()


def test_deactivate_own_account_commits():
    conn, cursor = _fake_conn()
    auth_db.deactivate_own_account(conn, 1)
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


# ── audit_db.py ─────────────────────────────────────────────────────────────────


def test_insert_audit_log_commits():
    from datetime import datetime

    conn, cursor = _fake_conn()
    audit_db.insert_audit_log(conn, "login", 1, "a@b.com", None, None, "success", "auth", "login", datetime.utcnow())
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_get_recent_audit_logs_returns_dicts():
    conn, _ = _fake_conn(fetchall=[{"id": 1}, {"id": 2}])
    rows = audit_db.get_recent_audit_logs(conn, 50)
    assert rows == [{"id": 1}, {"id": 2}]


def test_get_audit_logs_by_user():
    conn, _ = _fake_conn(fetchall=[{"id": 1, "user_id": 3}])
    rows = audit_db.get_audit_logs_by_user(conn, 3, 50)
    assert rows == [{"id": 1, "user_id": 3}]


# ── chat_db.py ──────────────────────────────────────────────────────────────────


def test_get_active_chat_session_found_and_absent():
    conn, _ = _fake_conn(fetchone={"id": 1, "user_id": 1})
    assert chat_db.get_active_chat_session(conn, 1) == {"id": 1, "user_id": 1}

    conn2, _ = _fake_conn(fetchone=None)
    assert chat_db.get_active_chat_session(conn2, 1) is None


def test_create_chat_session_commits_and_returns_id():
    conn, _ = _fake_conn(fetchone={"id": 7})
    assert chat_db.create_chat_session(conn, 1, "titulo") == 7
    conn.commit.assert_called_once()


def test_get_chat_session():
    conn, _ = _fake_conn(fetchone={"id": 1})
    assert chat_db.get_chat_session(conn, 1, 1) == {"id": 1}


def test_touch_chat_session_commits():
    conn, cursor = _fake_conn()
    chat_db.touch_chat_session(conn, 1, 1)
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_add_chat_message_commits_and_touches_session():
    conn, cursor = _fake_conn()
    chat_db.add_chat_message(conn, 1, 1, "user", "conteudo", "ok")
    assert cursor.execute.call_count == 2  # insert + touch_chat_session
    assert conn.commit.call_count == 2


def test_get_chat_messages_returns_list():
    conn, _ = _fake_conn(fetchall=[{"id": 1, "role": "user"}])
    rows = chat_db.get_chat_messages(conn, 1, 1)
    assert rows == [{"id": 1, "role": "user"}]


# ── users_db.py ─────────────────────────────────────────────────────────────────


def test_get_all_users_returns_list():
    conn, _ = _fake_conn(fetchall=[{"id": 1}, {"id": 2}])
    assert users_db.get_all_users(conn) == [{"id": 1}, {"id": 2}]


def test_update_user_role_commits():
    conn, cursor = _fake_conn()
    users_db.update_user_role(conn, 1, "admin")
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_update_audit_access_commits():
    conn, cursor = _fake_conn()
    users_db.update_audit_access(conn, 1, True)
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_soft_delete_user_commits():
    conn, cursor = _fake_conn()
    users_db.soft_delete_user(conn, 1)
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()
