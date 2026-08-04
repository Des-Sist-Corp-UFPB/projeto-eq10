"""Route-level tests via FastAPI's TestClient. Mocks at the service/DB boundary — no live
Postgres. TestClient persists cookies across requests on the same instance, so an
authenticated session is created once (via a mocked successful login) and reused.
"""

from __future__ import annotations

from unittest import mock

import pytest

from app.service.auth_service import AuthValidationError


# ── /estatisticas — public, no auth, no DB ────────────────────────────────────────


def test_estatisticas_returns_200(client):
    resp = client.get("/estatisticas")
    assert resp.status_code == 200
    assert "Mamanguape" in resp.text


def test_root_redirects_to_estatisticas(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"


# ── /auth/login, /auth/register, /auth/logout ─────────────────────────────────────


def test_get_login_renders(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 200
    assert "Entrar" in resp.text


def test_post_login_success_redirects_and_sets_cookie(client, fake_user):
    with mock.patch("app.service.auth_service.authenticate", return_value=fake_user):
        resp = client.post(
            "/auth/login",
            data={"email": "ana@example.com", "senha": "pw", "next": "/estatisticas"},
            follow_redirects=False,
        )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"
    assert "session" in resp.cookies


def test_post_login_failure_returns_400(client):
    with mock.patch("app.service.auth_service.authenticate", side_effect=AuthValidationError("E-mail ou senha inválidos.")):
        resp = client.post("/auth/login", data={"email": "ana@example.com", "senha": "wrong", "next": "/estatisticas"})
    assert resp.status_code == 400
    assert "inválidos" in resp.text


def test_get_register_renders(client):
    resp = client.get("/auth/register")
    assert resp.status_code == 200


def test_post_register_success_redirects(client, fake_user):
    with mock.patch("app.service.auth_service.register", return_value=fake_user):
        resp = client.post(
            "/auth/register",
            data={"nome": "Ana", "email": "ana@example.com", "senha": "senha12345", "confirmar_senha": "senha12345"},
            follow_redirects=False,
        )
    assert resp.status_code == 303


def test_post_register_failure_returns_400(client):
    with mock.patch("app.service.auth_service.register", side_effect=AuthValidationError("Já existe uma conta ativa com este e-mail.")):
        resp = client.post(
            "/auth/register",
            data={"nome": "Ana", "email": "ana@example.com", "senha": "senha12345", "confirmar_senha": "senha12345"},
        )
    assert resp.status_code == 400


def test_logout_clears_session(client, fake_user):
    with mock.patch("app.service.auth_service.authenticate", return_value=fake_user):
        client.post("/auth/login", data={"email": "ana@example.com", "senha": "pw", "next": "/estatisticas"})

    resp = client.post("/auth/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"

    # Session cookie is now cleared server-side; a protected page should redirect again.
    resp = client.get("/auth/profile", follow_redirects=False)
    assert resp.status_code == 303


def test_get_forgot_password_renders(client):
    resp = client.get("/auth/forgot-password")
    assert resp.status_code == 200


def test_post_forgot_password_shows_neutral_message(client):
    from app.service.auth_service import PasswordResetResult

    with mock.patch(
        "app.service.auth_service.request_password_reset",
        return_value=PasswordResetResult(True, "neutral", "Se houver uma conta com este e-mail, enviaremos instrucoes de recuperacao."),
    ):
        resp = client.post("/auth/forgot-password", data={"email": "nobody@example.com"})
    assert resp.status_code == 200
    assert "recuperacao" in resp.text.casefold() or "recupera" in resp.text.casefold()


def test_get_reset_password_invalid_token(client):
    from app.service.auth_service import PasswordResetResult

    with mock.patch(
        "app.service.auth_service.validate_reset_token",
        return_value=PasswordResetResult(False, "invalid", "Link de recuperacao invalido ou expirado."),
    ):
        resp = client.get("/auth/reset-password?reset_password_token=bogus")
    assert resp.status_code == 200
    assert "invalido" in resp.text.casefold() or "inválido" in resp.text.casefold()


def test_post_reset_password_success(client):
    from app.service.auth_service import PasswordResetResult

    with mock.patch(
        "app.service.auth_service.reset_password_with_token",
        return_value=PasswordResetResult(True, "reset", "Senha redefinida com sucesso."),
    ):
        resp = client.post(
            "/auth/reset-password",
            data={"reset_password_token": "tok", "nova_senha": "novaSenha1", "confirmar_senha": "novaSenha1"},
        )
    assert resp.status_code == 200
    assert "sucesso" in resp.text.casefold()


# ── /auth/profile (authenticated) ──────────────────────────────────────────────────


@pytest.fixture()
def logged_in_client(client, fake_user):
    with mock.patch("app.service.auth_service.authenticate", return_value=fake_user):
        client.post("/auth/login", data={"email": "ana@example.com", "senha": "pw", "next": "/estatisticas"})
    return client


def test_profile_requires_authentication(client):
    resp = client.get("/auth/profile", follow_redirects=False)
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_profile_renders_when_authenticated(logged_in_client):
    resp = logged_in_client.get("/auth/profile")
    assert resp.status_code == 200


def test_profile_update_name(logged_in_client, fake_user):
    updated = dict(fake_user, nome="Ana Maria")
    with mock.patch("app.service.auth_service.update_profile_name", return_value=updated):
        resp = logged_in_client.post("/auth/profile/name", data={"nome": "Ana Maria"}, follow_redirects=False)
    assert resp.status_code == 303


def test_profile_update_name_failure(logged_in_client):
    # The service layer is mocked to raise regardless of input — using a non-empty
    # placeholder here since some HTTP clients omit empty form fields entirely, which
    # would 422 on FastAPI's Form(...) validation before ever reaching the mock.
    with mock.patch("app.service.auth_service.update_profile_name", side_effect=AuthValidationError("Informe seu nome.")):
        resp = logged_in_client.post("/auth/profile/name", data={"nome": "x"})
    assert resp.status_code == 400


def test_profile_update_email(logged_in_client, fake_user):
    updated = dict(fake_user, email="nova@example.com")
    with mock.patch("app.service.auth_service.update_profile_email", return_value=updated):
        resp = logged_in_client.post("/auth/profile/email", data={"email": "nova@example.com"}, follow_redirects=False)
    assert resp.status_code == 303


def test_profile_update_password_success(logged_in_client):
    with mock.patch("app.service.auth_service.change_password", return_value=None):
        resp = logged_in_client.post(
            "/auth/profile/password",
            data={"senha_atual": "pw", "nova_senha": "novaSenha1", "confirmar_senha": "novaSenha1"},
        )
    assert resp.status_code == 200
    assert "sucesso" in resp.text.casefold()


def test_profile_update_password_failure(logged_in_client):
    with mock.patch("app.service.auth_service.change_password", side_effect=AuthValidationError("Senha atual invalida.")):
        resp = logged_in_client.post(
            "/auth/profile/password",
            data={"senha_atual": "wrong", "nova_senha": "novaSenha1", "confirmar_senha": "novaSenha1"},
        )
    assert resp.status_code == 400


def test_profile_deactivate(logged_in_client):
    with mock.patch("app.service.auth_service.deactivate_account", return_value=None):
        resp = logged_in_client.post("/auth/profile/deactivate", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"


# ── /chat ───────────────────────────────────────────────────────────────────────────


def test_chat_requires_authentication(client):
    resp = client.get("/chat", follow_redirects=False)
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_chat_ask_requires_authentication(client):
    resp = client.post("/chat/ask", data={"prompt": "quantos atendimentos?"})
    assert resp.status_code == 401


def test_chat_renders_when_authenticated(logged_in_client):
    # app/routes/chat.py opens its own connection directly (not through chat_service) for
    # GET /chat's history load — needs its own patch target, distinct from chat_service's.
    with mock.patch("app.routes.chat.get_auth_connection", return_value=mock.Mock(close=lambda: None)), \
         mock.patch("app.service.chat_service.load_message_history", return_value=[]):
        resp = logged_in_client.get("/chat")
    assert resp.status_code == 200
    assert "Chat IA" in resp.text


def test_chat_ask_success(logged_in_client):
    with mock.patch("app.routes.chat.get_auth_connection", return_value=mock.Mock(close=lambda: None)), \
         mock.patch("app.service.chat_service.get_or_create_active_session", return_value=1), \
         mock.patch("app.service.chat_service.save_message", return_value=None), \
         mock.patch("app.service.chat_service.process_question", return_value=("42", "ok")):
        resp = logged_in_client.post("/chat/ask", data={"prompt": "quantos atendimentos?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "42" in body["assistant_html"]


def test_chat_ask_empty_prompt_rejected(logged_in_client):
    resp = logged_in_client.post("/chat/ask", data={"prompt": "   "})
    assert resp.status_code == 400


# ── /auditoria ──────────────────────────────────────────────────────────────────────


def test_auditoria_requires_authentication(client):
    resp = client.get("/auditoria", follow_redirects=False)
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_auditoria_redirects_when_no_permission(logged_in_client):
    resp = logged_in_client.get("/auditoria", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"


@pytest.fixture()
def admin_client(client, fake_admin):
    with mock.patch("app.service.auth_service.authenticate", return_value=fake_admin):
        client.post("/auth/login", data={"email": "admin@example.com", "senha": "pw", "next": "/estatisticas"})
    return client


def test_auditoria_renders_for_admin(admin_client):
    with mock.patch("app.service.audit_service.get_recent_logs", return_value=[]):
        resp = admin_client.get("/auditoria")
    assert resp.status_code == 200
    assert "Auditoria" in resp.text


def test_auditoria_filtered_request(admin_client):
    with mock.patch("app.service.audit_service.get_recent_logs", return_value=[]):
        resp = admin_client.get("/auditoria", params={"event_type": "Login", "status": "success"})
    assert resp.status_code == 200


# ── /admin/users ────────────────────────────────────────────────────────────────────


def test_admin_users_requires_authentication(client):
    resp = client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 303
    assert "/auth/login" in resp.headers["location"]


def test_admin_users_redirects_when_not_super_admin(admin_client):
    resp = admin_client.get("/admin/users", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/estatisticas"


@pytest.fixture()
def super_admin_client(client, fake_super_admin):
    with mock.patch("app.service.auth_service.authenticate", return_value=fake_super_admin):
        client.post("/auth/login", data={"email": "root@example.com", "senha": "pw", "next": "/estatisticas"})
    return client


def test_admin_users_renders_for_super_admin(super_admin_client):
    with mock.patch("app.service.user_management_service.get_all_users", return_value=[]):
        resp = super_admin_client.get("/admin/users")
    assert resp.status_code == 200


def test_admin_users_role_change(super_admin_client, fake_user):
    with mock.patch("app.service.user_management_service.set_role", return_value=fake_user):
        resp = super_admin_client.post("/admin/users/1/role", data={"new_role": "admin"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "success" in resp.headers["location"]


def test_admin_users_role_change_invalid(super_admin_client):
    with mock.patch("app.service.user_management_service.set_role", side_effect=AuthValidationError("Papel invalido: bogus")):
        resp = super_admin_client.post("/admin/users/1/role", data={"new_role": "bogus"}, follow_redirects=False)
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_admin_users_audit_access_grant(super_admin_client):
    with mock.patch("app.service.user_management_service.set_audit_access", return_value=None):
        resp = super_admin_client.post("/admin/users/1/audit-access", data={"grant": "1"}, follow_redirects=False)
    assert resp.status_code == 303


def test_admin_users_deactivate(super_admin_client):
    with mock.patch("app.service.user_management_service.soft_delete_user", return_value=None):
        resp = super_admin_client.post("/admin/users/1/deactivate", follow_redirects=False)
    assert resp.status_code == 303


# ── /ping, /healthcheck, /health ──────────────────────────────────────────────────


def test_ping_returns_200_ok(client):
    resp = client.get("/ping")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_healthcheck_always_200(client):
    fake_result = mock.Mock()
    fake_result.as_dict.return_value = {"name": "heartbeat", "status": "ok", "message": "ok", "details": {}}
    with mock.patch("src.diagnostics.health_service.HealthService") as fake_service_cls:
        fake_service_cls.return_value.run_heartbeat.return_value = fake_result
        resp = client.get("/healthcheck")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_healthcheck_never_500s_on_exception(client):
    with mock.patch("src.diagnostics.health_service.HealthService", side_effect=RuntimeError("boom")):
        resp = client.get("/healthcheck")
    assert resp.status_code == 200
    assert resp.json()["status"] == "error"


def test_health_returns_200_when_db_reachable(client):
    fake_cursor = mock.MagicMock()
    fake_cursor.__enter__.return_value = fake_cursor
    fake_cursor.__exit__.return_value = False
    fake_conn = mock.Mock()
    fake_conn.cursor.return_value = fake_cursor

    with mock.patch("app.routes.healthcheck.get_auth_connection", return_value=fake_conn):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy", "database": "connected"}
    assert resp.headers["cache-control"] == "no-store"


def test_health_returns_503_when_db_unavailable(client):
    with mock.patch("app.routes.healthcheck.get_auth_connection", side_effect=RuntimeError("no route to host")):
        resp = client.get("/health")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unhealthy", "database": "unavailable"}


def test_health_never_leaks_exception_details(client):
    with mock.patch("app.routes.healthcheck.get_auth_connection", side_effect=RuntimeError("password=hunter2 host=secretdb.internal")):
        resp = client.get("/health")
    assert "hunter2" not in resp.text
    assert "secretdb" not in resp.text
