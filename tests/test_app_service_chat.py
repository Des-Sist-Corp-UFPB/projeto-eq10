"""app/service/chat_service.py — mocked app/database/chat_db.py, no live DB, no live AI layer."""

from __future__ import annotations

from datetime import datetime
from unittest import mock

import pytest

from app.service import chat_service


@pytest.fixture()
def sessions():
    return {}


@pytest.fixture()
def messages():
    return []


@pytest.fixture(autouse=True)
def patched_layer(sessions, messages, monkeypatch):
    next_id = [1]

    def fake_get_active_chat_session(conn, user_id):
        active = [s for s in sessions.values() if s["user_id"] == user_id]
        if not active:
            return None
        return max(active, key=lambda s: s["atualizado_em"])

    def fake_create_chat_session(conn, user_id, titulo):
        sid = next_id[0]
        next_id[0] += 1
        sessions[sid] = {"id": sid, "user_id": user_id, "titulo": titulo, "criado_em": datetime.utcnow(), "atualizado_em": datetime.utcnow()}
        return sid

    def fake_add_chat_message(conn, session_id, user_id, role, conteudo, status):
        messages.append({"id": len(messages) + 1, "chat_session_id": session_id, "user_id": user_id, "role": role, "conteudo": conteudo, "status": status, "criado_em": datetime.utcnow()})
        sessions[session_id]["atualizado_em"] = datetime.utcnow()

    def fake_get_chat_messages(conn, session_id, user_id):
        return [m for m in messages if m["chat_session_id"] == session_id and m["user_id"] == user_id]

    monkeypatch.setattr("app.database.chat_db.get_active_chat_session", fake_get_active_chat_session)
    monkeypatch.setattr("app.database.chat_db.create_chat_session", fake_create_chat_session)
    monkeypatch.setattr("app.database.chat_db.add_chat_message", fake_add_chat_message)
    monkeypatch.setattr("app.database.chat_db.get_chat_messages", fake_get_chat_messages)


def test_get_or_create_active_session_creates_then_reuses(sessions):
    conn = object()
    sid = chat_service.get_or_create_active_session(conn, 1, title="Valor aprovado por município")
    assert sid in sessions
    sid2 = chat_service.get_or_create_active_session(conn, 1)
    assert sid2 == sid


def test_save_message_redacts_sensitive_content(messages):
    conn = object()
    sid = chat_service.get_or_create_active_session(conn, 1)
    chat_service.save_message(conn, sid, 1, "user", "meu token=abc123secret e senha: hunter2", "ok")
    assert "[REDACTED]" in messages[0]["conteudo"]


def test_save_message_rejects_invalid_role():
    with pytest.raises(ValueError):
        chat_service.save_message(object(), 1, 1, "bogus-role", "x", "ok")


def test_save_message_normalizes_invalid_status(messages):
    conn = object()
    sid = chat_service.get_or_create_active_session(conn, 1)
    chat_service.save_message(conn, sid, 1, "assistant", "resposta", "not-a-real-status")
    assert messages[0]["status"] == "ok"


def test_load_message_history_empty_when_no_session():
    assert chat_service.load_message_history(object(), 999) == []


def test_load_message_history_returns_ordered_messages(messages):
    conn = object()
    sid = chat_service.get_or_create_active_session(conn, 1)
    chat_service.save_message(conn, sid, 1, "user", "pergunta", "ok")
    chat_service.save_message(conn, sid, 1, "assistant", "resposta", "ok")
    history = chat_service.load_message_history(conn, 1)
    assert [m["role"] for m in history] == ["user", "assistant"]


def test_process_question_success():
    with mock.patch("src.ai.datasus_ai.perguntar_datasus", return_value="42") as fake:
        resposta, status = chat_service.process_question("quantos atendimentos?", {"id": 1, "email": "a@b.com"})
    assert resposta == "42"
    assert status == "ok"
    fake.assert_called_once()


def test_process_question_handles_exception(monkeypatch):
    logged = []
    monkeypatch.setattr("app.service.audit_service.log_event_safely", lambda evento, **kw: logged.append((evento, kw)))
    with mock.patch("src.ai.datasus_ai.perguntar_datasus", side_effect=RuntimeError("boom")):
        resposta, status = chat_service.process_question("pergunta", {"id": 1, "email": "a@b.com"})
    assert status == "error"
    assert resposta == chat_service.GENERIC_ERROR_MESSAGE
    assert logged[0][0] == "chat_processing_error"


def test_redact_sensitive_content_various_patterns():
    text = "password: hunter2 reset_password_token=abc123 " + "f" * 50
    redacted = chat_service.redact_sensitive_content(text)
    assert "hunter2" not in redacted
    assert "abc123" not in redacted
    assert "[REDACTED_HASH]" in redacted


def test_sanitize_text_normalizes_whitespace_and_special_chars():
    assert chat_service.sanitize_text("a b—c…") == "a b-c..."
    assert chat_service.sanitize_text("line1\n\n\n\nline2") == "line1\n\nline2"


def test_friendly_response_blocks_unsafe_patterns():
    assert chat_service.friendly_response("Traceback: psycopg2.OperationalError") == chat_service.GENERIC_ERROR_MESSAGE


def test_friendly_response_empty_maps_to_unexpected_format():
    assert chat_service.friendly_response("") == chat_service.UNEXPECTED_FORMAT_ERROR_MESSAGE


def test_friendly_response_passes_through_normal_text():
    assert chat_service.friendly_response("Resultado: 42") == "Resultado: 42"


def test_render_assistant_content_number_card():
    html = chat_service.render_assistant_content("1234,56")
    assert 'class="assistant-result"' in html


def test_render_assistant_content_json_list():
    html = chat_service.render_assistant_content('["São Paulo", "Mamanguape"]')
    assert '<ul class="assistant-list">' in html
    assert "Mamanguape" in html


def test_render_assistant_content_markdown_table():
    md = "| Município | Total |\n| --- | --- |\n| Mamanguape | 120 |\n| Recife | 340 |"
    html = chat_service.render_assistant_content(md)
    assert "assistant-table" in html
    assert "Mamanguape" in html


def test_render_assistant_content_pair_lines():
    html = chat_service.render_assistant_content("- Masculino: 120\n- Feminino: 98")
    assert "assistant-table" in html
    assert "Masculino" in html


def test_render_assistant_content_plain_list():
    html = chat_service.render_assistant_content("- item um\n- item dois")
    assert "<ul" in html


def test_render_assistant_content_plain_paragraph():
    html = chat_service.render_assistant_content("Nenhum resultado encontrado para esse periodo.")
    assert "<p>" in html


def test_render_user_content_escapes_html():
    html = chat_service.render_user_content("<script>alert(1)</script>")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
