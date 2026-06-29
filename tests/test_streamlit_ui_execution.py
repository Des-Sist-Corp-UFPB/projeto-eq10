import unittest
from unittest.mock import MagicMock, patch

import app_ai_chat as app
from src.auth import roles
from src.ui import header, notifications, protected_chat, sidebar, statistics_page, styles


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeSt:
    def __init__(self):
        self.session_state = _State()
        self.query_params = {}
        self.markdowns = []
        self.buttons = []
        self.html_calls = []
        self.successes = []
        self.warnings = []
        self.errors = []
        self.clicked_keys = set()
        self.text_value = ""
        self.submitted = False

    def markdown(self, value, unsafe_allow_html=False):
        self.markdowns.append((value, unsafe_allow_html))

    def html(self, value):
        self.html_calls.append(value)

    def success(self, value):
        self.successes.append(value)

    def warning(self, value):
        self.warnings.append(value)

    def error(self, value):
        self.errors.append(value)

    def set_page_config(self, **kwargs):
        self.page_config = kwargs

    def columns(self, count, **kwargs):
        total = count if isinstance(count, int) else len(count)
        return [self for _ in range(total)]

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs))
        return kwargs.get("key") in self.clicked_keys

    def popover(self, *args, **kwargs):
        return self

    def form(self, *args, **kwargs):
        return self

    def text_input(self, *args, **kwargs):
        return self.text_value

    def form_submit_button(self, *args, **kwargs):
        return self.submitted

    def rerun(self):
        raise RuntimeError("rerun")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestStreamlitUiExecution(unittest.TestCase):
    def test_notifications_queue_build_and_render_success_toast(self):
        fake_st = _FakeSt()
        state = _State()
        fake_st.session_state = state

        notifications.queue_toast(state, "<ok>")
        with patch.object(notifications, "st", fake_st):
            notifications.render_pending_toast()

        self.assertIn("&lt;ok&gt;", fake_st.html_calls[0])
        self.assertNotIn(notifications.PENDING_TOAST_KEY, state)

    def test_sidebar_navigation_state_and_admin_item(self):
        fake_st = _FakeSt()
        fake_st.query_params["page"] = "chat-ia"
        admin_user = {"id": 1, "role": "admin", "can_view_audit": False}

        with patch.object(sidebar, "st", fake_st), patch.object(sidebar, "get_authenticated_user", return_value=admin_user):
            self.assertEqual(sidebar.get_current_page(), sidebar.CHAT_PAGE)
            sidebar.set_current_page(sidebar.ADMIN_PAGE)
            self.assertEqual(fake_st.query_params["page"], "auditoria")
            sidebar.render_sidebar(sidebar.ADMIN_PAGE)

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn("Auditoria", rendered)
        self.assertIn("nav-icon audit", rendered)
        self.assertNotIn("</nav>", rendered)

    def test_sidebar_public_fallbacks_and_button_navigation(self):
        fake_st = _FakeSt()
        fake_st.query_params["page"] = ["unknown"]
        fake_st.clicked_keys.add("sidebar-nav-chat-ia")

        with (
            patch.object(sidebar, "st", fake_st),
            patch.object(sidebar, "get_authenticated_user", return_value=None),
            patch.object(sidebar, "_get_sidebar_logo_data_uri", return_value=""),
        ):
            self.assertEqual(sidebar.get_current_page(), sidebar.DEFAULT_PAGE)
            with self.assertRaises(RuntimeError):
                sidebar.render_sidebar(sidebar.DEFAULT_PAGE)

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn("brand-logo-fallback", rendered)
        self.assertNotIn("Auditoria", rendered)
        self.assertEqual(fake_st.session_state.current_page, sidebar.CHAT_PAGE)
        self.assertEqual(fake_st.query_params["page"], "chat-ia")

    def test_sidebar_prefers_configured_public_logo_url(self):
        fake_st = _FakeSt()
        logo_url = "https://minio.example.test/public/logo.png"

        with (
            patch.object(sidebar, "st", fake_st),
            patch.object(sidebar, "get_authenticated_user", return_value=None),
            patch.object(sidebar, "_get_sidebar_logo_data_uri", return_value="data:image/png;base64,old"),
            patch.dict("os.environ", {"APP_LOGO_URL": logo_url}, clear=False),
        ):
            sidebar.render_sidebar(sidebar.DEFAULT_PAGE)

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn(logo_url, rendered)
        self.assertIn('<img class="brand-logo"', rendered)
        self.assertIn("brand-logo-fallback", rendered)
        self.assertIn("onerror=", rendered)

    def test_logo_url_config_accepts_only_safe_public_urls(self):
        self.assertEqual(
            styles.get_configured_logo_url({"APP_LOGO_URL": "https://minio.example.test/logo.png"}),
            "https://minio.example.test/logo.png",
        )
        self.assertEqual(styles.get_configured_logo_url({"APP_LOGO_URL": "javascript:alert(1)"}), "")
        self.assertEqual(styles.get_configured_logo_url({"APP_LOGO_URL": "file:///tmp/logo.png"}), "")

    def test_shared_light_styles_cover_deployed_dark_widget_overrides(self):
        self.assertIn("GLOBAL_LIGHT_THEME_CSS", styles.__dict__)
        self.assertIn("color-scheme: light", styles.GLOBAL_LIGHT_THEME_CSS)
        self.assertIn('[data-testid="stSelectbox"] div[data-baseweb="select"] > div', styles.GLOBAL_LIGHT_THEME_CSS)
        self.assertIn('[data-testid="stDataFrame"]', styles.GLOBAL_LIGHT_THEME_CSS)

    def test_header_logged_out_opens_login_and_logged_in_logout_queues_toast(self):
        fake_st = _FakeSt()
        fake_st.clicked_keys.add("auth-header-login")
        with (
            patch.object(header, "st", fake_st),
            patch.object(header, "get_authenticated_user", return_value=None),
            patch.object(header, "open_auth_modal") as open_modal,
        ):
            with self.assertRaises(RuntimeError):
                header.render_auth_header()

        open_modal.assert_called_once_with(mode="login")

        fake_st = _FakeSt()
        fake_st.clicked_keys.add("auth-menu-logout")
        user = {"id": 3, "nome": "Ana", "email": "ana@example.com"}
        with (
            patch.object(header, "st", fake_st),
            patch.object(header, "get_authenticated_user", return_value=user),
            patch.object(header, "_log_logout_audit") as audit,
            patch.object(header, "logout_session") as logout,
            patch.object(header, "set_auth_panel") as set_panel,
        ):
            with self.assertRaises(RuntimeError):
                header.render_auth_header()

        audit.assert_called_once_with(user)
        logout.assert_called_once_with(fake_st.session_state)
        set_panel.assert_called_once_with(None)
        self.assertIn("encerrada", fake_st.session_state[notifications.PENDING_TOAST_KEY])

    def test_logout_audit_success_and_failure_are_safe(self):
        event_recorder = MagicMock()
        audit_service = MagicMock(log_event=event_recorder)

        with patch("src.audit.audit_log_service.AuditLogService.from_environment", return_value=audit_service):
            header._log_logout_audit({"id": 4, "email": "ana@example.com"})

        event_recorder.assert_called_once()
        self.assertEqual(event_recorder.call_args.kwargs["user_id"], 4)

        with patch("src.audit.audit_log_service.AuditLogService.from_environment", side_effect=RuntimeError("db")):
            with self.assertLogs("src.ui.header", level="WARNING") as logs:
                header._log_logout_audit({"id": None, "email": "ana@example.com"})

        self.assertIn("audit_logout", "\n".join(logs.output))

    def test_statistics_page_renders_public_powerbi_link(self):
        fake_st = _FakeSt()
        with patch.object(statistics_page, "st", fake_st):
            statistics_page.render_statistics_page()

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn("Painel de Estat", rendered)
        self.assertIn(statistics_page.POWER_BI_URL, rendered)
        self.assertTrue(all(unsafe for _, unsafe in fake_st.markdowns))

    def test_role_helpers_cover_objects_dicts_and_unknown_roles(self):
        admin = {"role": roles.ROLE_ADMIN}
        super_admin = type("User", (), {"role": roles.ROLE_SUPER_ADMIN})()
        auditor = type("User", (), {"role": roles.ROLE_USER, "can_view_audit": True})()

        self.assertFalse(roles.can_view_audit_log(None))
        self.assertTrue(roles.is_admin(admin))
        self.assertTrue(roles.is_super_admin(super_admin))
        self.assertTrue(roles.can_view_audit_log(auditor))
        self.assertEqual(roles.role_display_name("custom"), "custom")

    def test_protected_chat_gate_opens_expected_auth_panels(self):
        fake_st = _FakeSt()
        fake_st.clicked_keys.add("chat-gate-signup")

        with patch.object(protected_chat, "st", fake_st), patch.object(protected_chat, "open_auth_modal") as open_modal:
            with self.assertRaises(RuntimeError):
                protected_chat.render_chat_auth_gate(open_login=True)

        self.assertEqual(open_modal.call_count, 2)
        self.assertEqual(open_modal.call_args.kwargs["mode"], "register")

        fake_st = _FakeSt()
        fake_st.clicked_keys.add("chat-gate-open-profile")
        with patch.object(protected_chat, "st", fake_st), patch.object(protected_chat, "set_auth_panel") as set_panel:
            with self.assertRaises(RuntimeError):
                protected_chat.render_chat_email_verification_gate()

        set_panel.assert_called_once_with("profile")

    def test_app_main_routes_default_chat_and_admin_without_external_calls(self):
        for page, expected_renderer in [
            (app.DEFAULT_PAGE, "statistics"),
            (app.CHAT_PAGE, "chat"),
            (app.ADMIN_PAGE, "admin"),
        ]:
            fake_st = _FakeSt()
            fake_st.session_state.current_page = page
            calls = {"statistics": 0, "chat": 0, "admin": 0}

            with (
                patch.object(app, "st", fake_st),
                patch.object(app, "render_pending_toast"),
                patch.object(app, "_handle_google_oauth_query_param"),
                patch.object(app, "_handle_password_reset_query_param"),
                patch.object(app, "_handle_email_verification_query_param"),
                patch.object(app, "render_auth_header"),
                patch.object(app, "render_auth_panel"),
                patch.object(app, "render_sidebar"),
                patch.object(app, "_render_admin_access_feedback"),
                patch.object(app, "get_current_page", return_value=page),
                patch.object(app, "_render_chat_page", side_effect=lambda: calls.__setitem__("chat", calls["chat"] + 1)),
                patch.object(app, "render_admin_page", side_effect=lambda: calls.__setitem__("admin", calls["admin"] + 1)),
                patch.object(app, "render_statistics_page", side_effect=lambda: calls.__setitem__("statistics", calls["statistics"] + 1)),
                patch.object(app, "_resolve_authorized_page", side_effect=lambda current: current),
            ):
                app.main()

            self.assertEqual(calls[expected_renderer], 1)
            self.assertEqual(fake_st.page_config["layout"], "wide")

    def test_chat_page_branches_for_anonymous_and_authenticated_users(self):
        fake_st = _FakeSt()
        fake_st.session_state.messages = []
        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=False),
            patch.object(app, "render_chat_auth_gate") as auth_gate,
        ):
            app._render_chat_page()

        auth_gate.assert_called_once_with(open_login=True)
        self.assertIsNone(fake_st.session_state.pending_prompt)

        fake_st = _FakeSt()
        fake_st.session_state.messages = []
        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=True),
            patch.object(app, "_process_pending_prompt", return_value=False),
        ):
            app._render_chat_page()

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn("Chat IA", rendered)
        self.assertTrue(any(label in app.EXAMPLE_PROMPTS for label, _ in fake_st.buttons))


if __name__ == "__main__":
    unittest.main()
