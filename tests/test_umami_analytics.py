from pathlib import Path

import pytest

from src.analytics import umami


class FakeStreamlit:
    def __init__(self):
        self.session_state = {}


@pytest.fixture
def configured_env(monkeypatch):
    monkeypatch.setenv("UMAMI_ENABLED", "true")
    monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://umami.dsc.rodrigor.com/script.js")
    monkeypatch.setenv("UMAMI_WEBSITE_ID", "339ab59d-d201-4b26-a7e5-e642385064f5")
    monkeypatch.setenv("UMAMI_HOST_URL", "https://umami.dsc.rodrigor.com")
    monkeypatch.setenv("UMAMI_ALLOWED_DOMAIN", "eq10.dsc.rodrigor.com")


def test_disabled_mode_does_not_render(monkeypatch):
    monkeypatch.setenv("UMAMI_ENABLED", "false")
    rendered = []
    status = umami.configure_umami(st_module=FakeStreamlit(), renderer=rendered.append)
    assert status.enabled is False
    assert rendered == []


@pytest.mark.parametrize("missing", ["UMAMI_SCRIPT_URL", "UMAMI_WEBSITE_ID"])
def test_missing_required_configuration_disables(monkeypatch, configured_env, missing):
    monkeypatch.delenv(missing)
    rendered = []
    status = umami.configure_umami(st_module=FakeStreamlit(), renderer=rendered.append)
    assert status.enabled is False
    assert rendered == []


def test_initialization_is_idempotent_per_streamlit_session(configured_env):
    fake = FakeStreamlit()
    rendered = []
    umami.configure_umami(st_module=fake, renderer=rendered.append)
    umami.configure_umami(st_module=fake, renderer=rendered.append)
    assert len(rendered) == 1
    assert 'data-auto-track", "false"' in rendered[0]
    assert "p.document.head.appendChild" in rendered[0]
    assert 'command.type === "page_view"' in rendered[0]
    assert "p.umami.track(props => ({" in rendered[0]
    assert 'command.type === "custom_event"' in rendered[0]
    assert "p.umami.track(command.name, command.data)" in rendered[0]


def test_page_views_are_deduplicated_until_page_changes(configured_env):
    fake = FakeStreamlit()
    rendered = []
    assert umami.track_page_view("/login", st_module=fake, renderer=rendered.append)
    assert not umami.track_page_view("/login", st_module=fake, renderer=rendered.append)
    assert umami.track_page_view("/chat-ia", st_module=fake, renderer=rendered.append)
    assert umami.track_page_view("/login", st_module=fake, renderer=rendered.append)
    payload = "\n".join(rendered)
    assert payload.count("/login") == 2
    assert payload.count("/chat-ia") == 1


@pytest.mark.parametrize(
    ("path", "json_title"),
    [
        ("/estatisticas", r"Estat\u00edsticas"),
        ("/login", "Login"),
        ("/cadastro", "Cadastro"),
        ("/recuperar-senha", "Recuperar senha"),
        ("/chat-ia", "Chat IA"),
        ("/auditoria", "Auditoria"),
        ("/administracao", r"Administra\u00e7\u00e3o"),
    ],
)
def test_page_view_uses_predefined_url_and_title(configured_env, path, json_title):
    fake = FakeStreamlit()
    rendered = []

    assert umami.track_page_view(path, st_module=fake, renderer=rendered.append)

    command = rendered[-1]
    assert '"type":"page_view"' in command
    assert f'"url":"{path}"' in command
    assert f'"title":"{json_title}"' in command
    assert '"name":' not in command
    assert '"type":"custom_event"' not in command


def test_page_view_rejects_query_parameters_and_sensitive_urls(configured_env):
    fake = FakeStreamlit()
    rendered = []

    assert not umami.track_page_view(
        "/login?email=pessoa@example.com&token=segredo",
        st_module=fake,
        renderer=rendered.append,
    )

    payload = "\n".join(rendered)
    assert "pessoa@example.com" not in payload
    assert "segredo" not in payload
    assert "?" not in payload


@pytest.mark.parametrize(
    "name",
    [
        "login_succeeded",
        "login_failed",
        "ai_question_submitted",
        "ai_question_blocked",
        "ai_question_failed",
    ],
)
def test_required_safe_events_are_emitted(configured_env, name):
    fake = FakeStreamlit()
    rendered = []
    assert umami.track_event(name, {"result": "failure"}, st_module=fake, renderer=rendered.append)
    command = rendered[-1]
    assert '"type":"custom_event"' in command
    assert f'"name":"{name}"' in command
    assert '"type":"page_view"' not in command
    assert '"url":' not in command


def test_sensitive_or_arbitrary_payloads_are_rejected(configured_env):
    fake = FakeStreamlit()
    rendered = []
    sensitive = {
        "prompt": "ignore as regras",
        "email": "pessoa@example.com",
        "password": "segredo",
        "token": "abc",
    }
    for key, value in sensitive.items():
        assert not umami.track_event(
            "login_failed", {key: value}, st_module=fake, renderer=rendered.append
        )
    assert not umami.track_event(
        "evento_inventado", {"result": "success"}, st_module=fake, renderer=rendered.append
    )
    assert "pessoa@example.com" not in "\n".join(rendered)


def test_renderer_failure_never_escapes(configured_env):
    def fail(_markup):
        raise RuntimeError("network-secret")

    fake = FakeStreamlit()
    status = umami.configure_umami(st_module=fake, renderer=fail)
    assert status.enabled
    assert not umami.track_event(
        "login_failed", {"result": "failure"}, st_module=fake, renderer=fail
    )
    assert not umami.track_page_view("/login", st_module=fake, renderer=fail)


def test_safe_masked_status(configured_env):
    umami.configure_umami(st_module=FakeStreamlit(), renderer=lambda _: None)
    status = umami.get_umami_status()
    assert status["masked_website_id"] == "339ab59d-****-****-****-e642385064f5"
    assert "script_url" not in status
    assert "host_url" not in status


def test_production_configuration_and_documentation_are_safe():
    compose = Path("docker-compose.prod.yml").read_text(encoding="utf-8")
    example = Path(".env.example").read_text(encoding="utf-8")
    docs = Path("docs/UMAMI_ANALYTICS.md").read_text(encoding="utf-8")
    assert "UMAMI_ENABLED" in compose
    assert "UMAMI_WEBSITE_ID" in compose
    assert "UMAMI_WEBSITE_ID=" in example
    assert "validacao" in docs.lower()
    combined = (compose + example + docs).lower()
    assert "umami_panel_password" not in combined
    assert "umami_password" not in combined


def test_business_event_wiring_contains_no_user_payload_fields():
    app = Path("app_ai_chat.py").read_text(encoding="utf-8")
    auth = Path("src/ui/auth_modal.py").read_text(encoding="utf-8")
    assert 'track_event("ai_question_submitted", {"page": "chat"})' in app
    assert 'track_event("ai_question_blocked", {"result": "blocked"})' in app
    assert 'track_event("ai_question_failed", {"result": "failure"})' in app
    assert 'track_event("login_succeeded", {"result": "success"})' in auth
    assert 'track_event("login_failed", {"result": "failure"})' in auth
    analytics_calls = "\n".join(
        line for line in (app + auth).splitlines() if "track_event(" in line
    )
    for forbidden in (
        '{"prompt"',
        '{"email"',
        '{"senha"',
        '{"password"',
        '{"token"',
        '{"user_id"',
    ):
        assert forbidden not in analytics_calls.lower()
