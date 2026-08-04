"""app/service/audit_service.py — mocked app/database/audit_db.py, no live DB."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.service import audit_service


class FakeConn:
    def close(self):
        pass

    def commit(self):
        pass


@pytest.fixture()
def inserted():
    return []


@pytest.fixture(autouse=True)
def patched_layer(inserted, monkeypatch):
    def fake_get_auth_connection():
        return FakeConn()

    def fake_insert_audit_log(conn, evento, user_id, user_email, prompt_text, detalhe, status, source, action, criado_em):
        inserted.append(
            {
                "evento": evento, "user_id": user_id, "user_email": user_email, "prompt_text": prompt_text,
                "detalhe": detalhe, "status": status, "source": source, "action": action, "criado_em": criado_em,
            }
        )

    monkeypatch.setattr("app.service.audit_service.get_auth_connection", fake_get_auth_connection)
    monkeypatch.setattr("app.service.audit_service.insert_audit_log", fake_insert_audit_log)


ENTRIES = [
    {"id": 1, "evento": "login", "user_id": 1, "user_email": "ana@example.com", "prompt_text": None,
     "detalhe": None, "status": "success", "source": "auth", "action": "login", "criado_em": datetime(2026, 7, 1, 10, 0)},
    {"id": 2, "evento": "login_failure", "user_id": None, "user_email": "bob@example.com", "prompt_text": None,
     "detalhe": "motivo=credenciais_invalidas", "status": "failure", "source": "auth", "action": "login", "criado_em": datetime(2026, 7, 2, 11, 0)},
    {"id": 3, "evento": "prompt_guard_block", "user_id": 1, "user_email": "ana@example.com", "prompt_text": "DROP TABLE",
     "detalhe": "regra=sql_injection", "status": "blocked", "source": "ai", "action": "prompt_guard", "criado_em": datetime(2026, 7, 3, 9, 30)},
    {"id": 4, "evento": "role_changed", "user_id": 2, "user_email": "carol@example.com", "prompt_text": None,
     "detalhe": "novo_role=admin | admin_id=1 | admin=ana@example.com", "status": "info", "source": "admin", "action": "role_changed", "criado_em": datetime(2026, 7, 4, 14, 0)},
    {"id": 5, "evento": "password_reset_requested", "user_id": 3, "user_email": "dave@example.com", "prompt_text": None,
     "detalhe": "status=sent; mode=smtp; sent=True", "status": "info", "source": "auth", "action": "password_reset_request", "criado_em": datetime(2026, 7, 5, 8, 0)},
    {"id": 6, "evento": "logout", "user_id": 1, "user_email": "ana@example.com", "prompt_text": None,
     "detalhe": None, "status": "info", "source": "auth", "action": "logout", "criado_em": datetime(2026, 7, 6, 18, 0)},
]


def test_log_event_rejects_unknown_event(inserted):
    audit_service.log_event_safely("not_a_real_event", user_email="x@example.com")
    assert inserted == []


def test_log_event_safely_inserts_sanitized_row(inserted):
    audit_service.log_event_safely(
        audit_service.EVENT_LOGIN,
        user_id=1,
        user_email="ana@example.com",
        detalhe="password=hunter2 token=abc123456",
        status="success",
        source="auth",
        action="login",
    )
    assert len(inserted) == 1
    assert "hunter2" not in inserted[0]["detalhe"]
    assert "[oculto]" in inserted[0]["detalhe"]
    assert inserted[0]["evento"] == "login"


def test_log_event_status_falls_back_to_inferred_when_invalid(inserted):
    audit_service.log_event_safely(audit_service.EVENT_LOGOUT, status="not-a-real-status")
    assert inserted[0]["status"] == "info"


def test_log_event_safely_never_raises_on_connection_failure(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.service.audit_service.get_auth_connection", boom)
    audit_service.log_event_safely(audit_service.EVENT_LOGIN)  # must not raise


def test_sanitize_text_redacts_secrets_and_connection_strings():
    text = audit_service.sanitize_text("password=hunter2 postgresql://user:pw@host/db Bearer abcdef123456")
    assert "hunter2" not in text
    assert "postgresql://" not in text
    assert "[oculto]" in text
    assert "[db-url-oculta]" in text


def test_sanitize_text_none_returns_none():
    assert audit_service.sanitize_text(None) is None


def test_build_summary():
    summary = audit_service.build_summary(ENTRIES)
    assert summary == {"total": 6, "logins": 2, "failures": 1, "blocked_prompts": 1}


@pytest.mark.parametrize(
    "index,expected",
    [(0, "Login"), (2, "Prompt bloqueado"), (3, "Administracao"), (4, "Conta"), (5, "Login")],
)
def test_event_category(index, expected):
    assert audit_service.event_category(ENTRIES[index]) == expected


def test_event_category_outros_for_unmatched_event():
    assert audit_service.event_category({"evento": "something_else"}) == "Outros"


def test_entry_status_prefers_stored_status():
    assert audit_service.entry_status({"evento": "login", "status": "blocked"}) == "blocked"


def test_entry_status_infers_when_missing():
    assert audit_service.entry_status({"evento": "login_failure", "status": None}) == "failure"


def test_status_label_mapping():
    assert audit_service.status_label("success") == "Sucesso"
    assert audit_service.status_label("failure") == "Falha"
    assert audit_service.status_label("blocked") == "Bloqueado"
    assert audit_service.status_label("info") == "Informativo"
    assert audit_service.status_label("garbage") == "Informativo"


def test_event_label_login_failure_and_success():
    assert audit_service.event_label({"evento": "login", "status": "failure"}) == "Falha no login"
    assert audit_service.event_label({"evento": "login", "status": "success"}) == "Login realizado"
    assert audit_service.event_label({"evento": "role_changed", "status": "info"}) == "Papel alterado"
    assert audit_service.event_label({"evento": "totally_unknown_event", "status": "info"}) == "totally_unknown_event"


def test_format_dt_none_and_value():
    assert audit_service.format_dt(None) == "-"
    assert audit_service.format_dt(datetime(2026, 7, 1, 10, 0)) == "01/07/2026 10:00:00"


def test_filter_entries_by_category():
    result = audit_service.filter_entries(ENTRIES, event_type="Login")
    assert {e["id"] for e in result} == {1, 2, 6}


def test_filter_entries_by_status():
    result = audit_service.filter_entries(ENTRIES, status="blocked")
    assert {e["id"] for e in result} == {3}


def test_filter_entries_by_user_search():
    result = audit_service.filter_entries(ENTRIES, user_search="ana@")
    assert {e["id"] for e in result} == {1, 3, 6}


def test_filter_entries_by_date_range():
    result = audit_service.filter_entries(ENTRIES, start_date=date(2026, 7, 3), end_date=date(2026, 7, 4))
    assert {e["id"] for e in result} == {3, 4}


def test_filter_entries_todos_returns_all():
    assert len(audit_service.filter_entries(ENTRIES)) == len(ENTRIES)


def test_format_entry_for_display_basic_fields():
    display = audit_service.format_entry_for_display(ENTRIES[3])
    assert display["evento"] == "Papel alterado"
    assert display["status_label"] == "Informativo"
    assert "role_changed" in display["metadados"]


def test_format_entry_for_display_redacts_sensitive_detail():
    sensitive = {
        "id": 7, "evento": "email_sending_failure", "user_id": None, "user_email": "x@example.com",
        "prompt_text": None, "detalhe": "password=hunter2 token=abcdef123456", "status": "failure",
        "source": "email", "action": "password_reset", "criado_em": datetime(2026, 7, 7, 0, 0),
    }
    display = audit_service.format_entry_for_display(sensitive)
    assert "hunter2" not in display["detalhe_full"]
    assert "[oculto]" in display["detalhe_full"]


def test_get_recent_logs_calls_database_layer(monkeypatch):
    monkeypatch.setattr(
        "app.service.audit_service.get_recent_audit_logs",
        lambda conn, limit: [{"id": 1, "evento": "login"}],
    )
    logs = audit_service.get_recent_logs(50)
    assert logs == [{"id": 1, "evento": "login"}]


def test_sanitize_display_text_truncates_and_flags_technical_errors():
    assert audit_service.sanitize_display_text(None) == "-"
    assert audit_service.sanitize_display_text("") == "-"
    assert audit_service.sanitize_display_text("Traceback (most recent call last)") == "Erro tecnico registrado com seguranca."
    long_text = "x" * 200
    truncated = audit_service.sanitize_display_text(long_text, max_len=90)
    assert truncated.endswith("...")
    assert truncated.startswith("x" * 89)
    assert len(truncated) < len(long_text)
