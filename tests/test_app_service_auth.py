"""app/service/auth_service.py — mocked app/database/auth_db.py + connection, no live DB."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest import mock

import pytest

from app.service import auth_service


class FakeConn:
    def close(self):
        pass


@pytest.fixture()
def users():
    return {}


@pytest.fixture()
def reset_tokens():
    return {}


@pytest.fixture()
def audit_events():
    return []


@pytest.fixture(autouse=True)
def patched_layer(users, reset_tokens, audit_events, monkeypatch):
    next_id = [1]

    def fake_get_auth_connection():
        return FakeConn()

    def fake_get_user_by_email(conn, email):
        for u in users.values():
            if u["email"] == email:
                return dict(u)
        return None

    def fake_get_user_by_id(conn, user_id):
        u = users.get(user_id)
        return dict(u) if u else None

    def fake_active_email_exists(conn, email, *, exclude_user_id=None):
        return any(u["email"] == email and uid != exclude_user_id for uid, u in users.items())

    def fake_create_user(conn, nome, email, senha_hash, role):
        uid = next_id[0]
        next_id[0] += 1
        users[uid] = {
            "id": uid, "nome": nome, "email": email, "senha_hash": senha_hash, "role": role,
            "criado_em": datetime.utcnow(), "atualizado_em": datetime.utcnow(), "ultimo_login_em": None,
            "can_view_audit": False, "email_verificado": False,
        }
        return uid

    def fake_update_last_login(conn, user_id):
        users[user_id]["ultimo_login_em"] = datetime.utcnow()

    def fake_update_user_name(conn, user_id, nome):
        users[user_id]["nome"] = nome

    def fake_update_user_email(conn, user_id, email):
        users[user_id]["email"] = email
        users[user_id]["email_verificado"] = False

    def fake_get_password_hash(conn, user_id):
        return users[user_id]["senha_hash"]

    def fake_update_user_password(conn, user_id, senha_hash):
        users[user_id]["senha_hash"] = senha_hash

    def fake_update_active_user_password(conn, user_id, senha_hash):
        if user_id in users:
            users[user_id]["senha_hash"] = senha_hash
            return 1
        return 0

    def fake_deactivate_own_account(conn, user_id):
        users.pop(user_id, None)

    def fake_create_password_reset_token(conn, user_id, token_hash, criado_em, expira_em):
        reset_tokens[token_hash] = {"id": len(reset_tokens) + 1, "user_id": user_id, "expira_em": expira_em, "usado_em": None}

    def fake_get_password_reset_token_by_hash(conn, token_hash):
        row = reset_tokens.get(token_hash)
        return dict(row) if row else None

    def fake_mark_password_reset_token_used(conn, token_id, usado_em):
        for row in reset_tokens.values():
            if row["id"] == token_id:
                row["usado_em"] = usado_em

    def fake_log_event_safely(evento, **kwargs):
        audit_events.append((evento, kwargs))

    # auth_service.py does `from app.database.connection import get_auth_connection`, so the
    # name is bound into ITS OWN module namespace — patching app.database.connection's copy
    # wouldn't affect the already-imported reference auth_service actually calls.
    monkeypatch.setattr("app.service.auth_service.get_auth_connection", fake_get_auth_connection)
    monkeypatch.setattr("app.database.auth_db.get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr("app.database.auth_db.get_user_by_id", fake_get_user_by_id)
    monkeypatch.setattr("app.database.auth_db.active_email_exists", fake_active_email_exists)
    monkeypatch.setattr("app.database.auth_db.create_user", fake_create_user)
    monkeypatch.setattr("app.database.auth_db.update_last_login", fake_update_last_login)
    monkeypatch.setattr("app.database.auth_db.update_user_name", fake_update_user_name)
    monkeypatch.setattr("app.database.auth_db.update_user_email", fake_update_user_email)
    monkeypatch.setattr("app.database.auth_db.get_password_hash", fake_get_password_hash)
    monkeypatch.setattr("app.database.auth_db.update_user_password", fake_update_user_password)
    monkeypatch.setattr("app.database.auth_db.update_active_user_password", fake_update_active_user_password)
    monkeypatch.setattr("app.database.auth_db.deactivate_own_account", fake_deactivate_own_account)
    monkeypatch.setattr("app.database.auth_db.create_password_reset_token", fake_create_password_reset_token)
    monkeypatch.setattr("app.database.auth_db.get_password_reset_token_by_hash", fake_get_password_reset_token_by_hash)
    monkeypatch.setattr("app.database.auth_db.mark_password_reset_token_used", fake_mark_password_reset_token_used)
    monkeypatch.setattr("app.service.audit_service.log_event_safely", fake_log_event_safely)


def test_register_creates_user_and_normalizes_email(users, audit_events):
    user = auth_service.register("Ana Silva", "Ana@Example.com ", "senha12345", "senha12345")
    assert user["email"] == "ana@example.com"
    assert users[user["id"]]["role"] == "user"
    assert audit_events[0][0] == "account_created"


def test_register_rejects_duplicate_active_email(users):
    auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.register("Ana2", "ana@example.com", "senha12345", "senha12345")


def test_register_rejects_short_password():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.register("Ana", "ana@example.com", "short", "short")


def test_register_rejects_mismatched_confirmation():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.register("Ana", "ana@example.com", "senha12345", "different1")


def test_register_rejects_blank_name():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.register("   ", "ana@example.com", "senha12345", "senha12345")


def test_register_rejects_invalid_email():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.register("Ana", "not-an-email", "senha12345", "senha12345")


def test_authenticate_success(audit_events):
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    logged_in = auth_service.authenticate("ana@example.com", "senha12345")
    assert logged_in["id"] == user["id"]
    assert any(evt == "login" for evt, _ in audit_events)


def test_authenticate_wrong_password_raises(audit_events):
    auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.authenticate("ana@example.com", "wrong-password")
    assert any(evt == "login_failure" for evt, _ in audit_events)


def test_authenticate_unknown_email_raises(audit_events):
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.authenticate("nobody@example.com", "senha12345")
    assert any(evt == "login_failure" for evt, _ in audit_events)


def test_authenticate_missing_password_raises(audit_events):
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.authenticate("ana@example.com", "")
    assert any(evt == "login_failure" and kw.get("detalhe") == "motivo=senha_ausente" for evt, kw in audit_events)


def test_update_profile_name_and_email():
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    updated = auth_service.update_profile_name(user["id"], "  Ana Maria  ")
    assert updated["nome"] == "Ana Maria"

    updated = auth_service.update_profile_email(user["id"], "ana.nova@example.com")
    assert updated["email"] == "ana.nova@example.com"


def test_update_profile_email_rejects_duplicate():
    auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    bob = auth_service.register("Bob", "bob@example.com", "senha12345", "senha12345")
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.update_profile_email(bob["id"], "ana@example.com")


def test_change_password_success_and_relogin():
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    auth_service.change_password(user["id"], "senha12345", "novaSenha999", "novaSenha999")
    assert auth_service.authenticate("ana@example.com", "novaSenha999")


def test_change_password_wrong_current_raises():
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.change_password(user["id"], "wrong-current", "abc12345", "abc12345")


def test_deactivate_account_prevents_future_login(audit_events):
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")
    auth_service.deactivate_account(user)
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.authenticate("ana@example.com", "senha12345")
    assert any(evt == "account_deleted" for evt, _ in audit_events)


def test_password_reset_full_cycle():
    user = auth_service.register("Ana", "ana@example.com", "senha12345", "senha12345")

    with mock.patch("app.service.email_service.EmailService.send_password_reset_email") as send_mock:
        from app.service.email_service import EmailSendResult

        send_mock.return_value = EmailSendResult(True, False, "fake", "fake", "ok")
        result = auth_service.request_password_reset("ana@example.com")
        assert result.success
        assert send_mock.called

    from urllib.parse import parse_qs, urlsplit

    reset_target = send_mock.call_args[0][1]
    raw_token = parse_qs(urlsplit(reset_target).query)["reset_password_token"][0]

    validation = auth_service.validate_reset_token(raw_token)
    assert validation.success

    reset_result = auth_service.reset_password_with_token(raw_token, "resetadaSenha1", "resetadaSenha1")
    assert reset_result.success
    assert auth_service.authenticate("ana@example.com", "resetadaSenha1")

    reused = auth_service.reset_password_with_token(raw_token, "outraSenha1", "outraSenha1")
    assert not reused.success
    assert reused.status == "used"


def test_request_password_reset_unknown_email_is_neutral():
    result = auth_service.request_password_reset("nobody@example.com")
    assert result.success
    assert result.status == "not_found"
    assert result.message == auth_service.PASSWORD_RESET_NEUTRAL_MESSAGE


def test_request_password_reset_invalid_email_is_neutral():
    result = auth_service.request_password_reset("not-an-email")
    assert result.success
    assert result.status == "neutral"


def test_validate_reset_token_blank_is_invalid():
    result = auth_service.validate_reset_token("")
    assert not result.success
    assert result.status == "invalid"


def test_validate_reset_token_unknown_is_invalid():
    result = auth_service.validate_reset_token("bogus-token-value")
    assert not result.success
    assert result.status == "invalid"


def test_reset_password_with_token_rejects_short_password():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.reset_password_with_token("sometoken", "short", "short")


def test_reset_password_with_token_rejects_mismatch():
    with pytest.raises(auth_service.AuthValidationError):
        auth_service.reset_password_with_token("sometoken", "senha12345", "different1")


def test_reset_password_with_token_blank_token():
    result = auth_service.reset_password_with_token("", "senha12345", "senha12345")
    assert not result.success
    assert result.status == "invalid"


def test_logout_logs_event_when_user_present(audit_events):
    auth_service.logout({"id": 1, "email": "ana@example.com"})
    assert audit_events[0][0] == "logout"


def test_logout_noop_when_no_user(audit_events):
    auth_service.logout(None)
    assert audit_events == []


def test_normalize_email_strips_and_casefolds():
    assert auth_service.normalize_email("  Ana@EXAMPLE.com ") == "ana@example.com"
