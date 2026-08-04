"""app/service/user_management_service.py — mocked database layer, no live DB."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import pytest

from app.service import user_management_service
from app.service.auth_service import AuthValidationError


@pytest.fixture()
def users():
    return {
        1: {"id": 1, "nome": "Admin", "email": "admin@example.com", "role": "super_admin", "criado_em": datetime(2026, 1, 1), "atualizado_em": datetime(2026, 1, 1), "ultimo_login_em": None, "can_view_audit": True},
        2: {"id": 2, "nome": "Carol", "email": "carol@example.com", "role": "user", "criado_em": datetime(2026, 1, 2), "atualizado_em": datetime(2026, 1, 2), "ultimo_login_em": None, "can_view_audit": False},
    }


@pytest.fixture()
def audit_events():
    return []


@pytest.fixture(autouse=True)
def patched_layer(users, audit_events, monkeypatch):
    def fake_get_all_users(conn):
        return list(users.values())

    def fake_update_user_role(conn, user_id, new_role):
        users[user_id]["role"] = new_role

    def fake_update_audit_access(conn, user_id, can_view_audit):
        users[user_id]["can_view_audit"] = can_view_audit

    def fake_soft_delete_user(conn, user_id):
        users.pop(user_id, None)

    def fake_get_user_by_id(conn, user_id):
        return users.get(user_id)

    def fake_log_event_safely(evento, **kwargs):
        audit_events.append((evento, kwargs))

    monkeypatch.setattr("app.database.users_db.get_all_users", fake_get_all_users)
    monkeypatch.setattr("app.database.users_db.update_user_role", fake_update_user_role)
    monkeypatch.setattr("app.database.users_db.update_audit_access", fake_update_audit_access)
    monkeypatch.setattr("app.database.users_db.soft_delete_user", fake_soft_delete_user)
    monkeypatch.setattr("app.database.auth_db.get_user_by_id", fake_get_user_by_id)
    monkeypatch.setattr("app.service.user_management_service.get_auth_connection", lambda: Mock(close=lambda: None))
    monkeypatch.setattr("app.service.audit_service.log_event_safely", fake_log_event_safely)


def test_get_all_users(users):
    result = user_management_service.get_all_users()
    assert len(result) == 2


def test_set_role_updates_and_logs(users, audit_events):
    updated = user_management_service.set_role(2, "admin", 1, "admin@example.com")
    assert updated["role"] == "admin"
    assert audit_events[0][0] == "role_changed"
    assert "novo_role=admin" in audit_events[0][1]["detalhe"]


def test_set_role_rejects_invalid_role():
    with pytest.raises(AuthValidationError):
        user_management_service.set_role(2, "not-a-real-role", 1, "admin@example.com")


def test_set_audit_access_grant_and_revoke(users, audit_events):
    user_management_service.set_audit_access(2, True, 1, "admin@example.com")
    assert users[2]["can_view_audit"] is True
    assert audit_events[-1][0] == "access_granted"

    user_management_service.set_audit_access(2, False, 1, "admin@example.com")
    assert users[2]["can_view_audit"] is False
    assert audit_events[-1][0] == "access_revoked"


def test_soft_delete_user_removes_and_logs(users, audit_events):
    user_management_service.soft_delete_user(2)
    assert 2 not in users
    assert audit_events[0][0] == "account_deleted"
    assert audit_events[0][1]["user_email"] == "carol@example.com"
