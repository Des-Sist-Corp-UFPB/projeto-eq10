from types import SimpleNamespace
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import src.ui.admin_page as admin_page


ADMIN_PAGE_PATH = Path("src/ui/admin_page.py")
STREAMLIT_CONFIG_PATH = Path(".streamlit/config.toml")


class _FakeStreamlit:
    def __init__(self):
        self.markdowns = []
        self.infos = []
        self.metrics = []
        self.dataframes = []
        self.subheaders = []
        self.captions = []
        self.buttons = []
        self.texts = []
        self.writes = []
        self.successes = []
        self.errors = []
        self.warnings = []
        self.session_state = {}
        self.clicked_keys = set()
        self.rerun_called = False
        self.badges = []
        self.dialogs = []
        self.cache_resource = SimpleNamespace(clear=MagicMock())

    def markdown(self, body, unsafe_allow_html=False):
        self.markdowns.append((body, unsafe_allow_html))

    def info(self, message):
        self.infos.append(message)

    def success(self, message):
        self.successes.append(message)

    def error(self, message):
        self.errors.append(message)

    def warning(self, message):
        self.warnings.append(message)

    def caption(self, message):
        self.captions.append(message)

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs))
        return kwargs.get("key") in self.clicked_keys

    def columns(self, count, **kwargs):
        if isinstance(count, int):
            total = count
        else:
            total = len(count)
        return [self for _ in range(total)]

    def metric(self, label, value):
        self.metrics.append((label, value))

    def dataframe(self, data, **kwargs):
        self.dataframes.append((data, kwargs))

    def selectbox(self, label, options, index=0, **kwargs):
        if kwargs.get("key") in self.session_state:
            return self.session_state[kwargs["key"]]
        return options[index] if options else None

    def subheader(self, text):
        self.subheaders.append(text)

    def title(self, text):
        self.texts.append(text)

    def divider(self):
        self.texts.append("---")

    def container(self, **kwargs):
        return self

    def expander(self, *args, **kwargs):
        return self

    def text(self, value):
        self.texts.append(value)

    def write(self, value):
        self.writes.append(value)

    def badge(self, label, **kwargs):
        self.badges.append((label, kwargs))

    def dialog(self, title, **kwargs):
        self.dialogs.append((title, kwargs))

        def decorator(func):
            def wrapper():
                return func()

            return wrapper

        return decorator

    def text_input(self, label, value="", **kwargs):
        return value

    def date_input(self, label, value=None, **kwargs):
        return value

    def stop(self):
        raise RuntimeError("streamlit stop")

    def rerun(self):
        self.rerun_called = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def _dataframe_records(data):
    if hasattr(data, "data") and hasattr(data.data, "to_dict"):
        return data.data.to_dict(orient="records")
    if hasattr(data, "to_dict"):
        return data.to_dict(orient="records")
    return data


class TestAdminPageUi(unittest.TestCase):
    def test_audit_page_forces_light_streamlit_widgets(self):
        config_source = STREAMLIT_CONFIG_PATH.read_text(encoding="utf-8")
        admin_source = ADMIN_PAGE_PATH.read_text(encoding="utf-8")

        self.assertIn('base = "light"', config_source)
        self.assertIn('backgroundColor = "#F8FAFC"', config_source)
        self.assertIn('secondaryBackgroundColor = "#FFFFFF"', config_source)
        self.assertIn('[data-testid="stDataFrame"]', admin_source)
        self.assertIn('[data-testid="stDateInput"] input', admin_source)
        self.assertIn('[data-testid="stSelectbox"] div[data-baseweb="select"] > div', admin_source)
        self.assertIn("background: #FFFFFF !important", admin_source)

    def test_audit_status_labels_and_colors_are_standardized(self):
        cases = {
            "success": ("success", "Sucesso", "#DCFCE7", "#166534"),
            "sucesso": ("success", "Sucesso", "#DCFCE7", "#166534"),
            "failure": ("failure", "Falha", "#FEE2E2", "#991B1B"),
            "falha": ("failure", "Falha", "#FEE2E2", "#991B1B"),
            "erro": ("failure", "Falha", "#FEE2E2", "#991B1B"),
            "blocked": ("blocked", "Bloqueado", "#FEF3C7", "#92400E"),
            "bloqueado": ("blocked", "Bloqueado", "#FEF3C7", "#92400E"),
            "info": ("info", "Informativo", "#DBEAFE", "#1E40AF"),
            "informativo": ("info", "Informativo", "#DBEAFE", "#1E40AF"),
        }

        for raw_status, (normalized, label, background, text_color) in cases.items():
            with self.subTest(raw_status=raw_status):
                self.assertEqual(admin_page._normalize_status(raw_status), normalized)
                self.assertEqual(admin_page._audit_status_label(raw_status), label)
                style = admin_page._get_status_badge_style(raw_status)
                self.assertIn(background, style)
                self.assertIn(text_color, style)

    def test_audit_summary_empty_logs_does_not_crash(self):
        fake_st = _FakeStreamlit()

        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_summary([])

        self.assertEqual(
            fake_st.metrics,
            [
                ("Total de eventos", 0),
                ("Logins", 0),
                ("Falhas", 0),
                ("Prompts bloqueados", 0),
            ],
        )

    def test_audit_table_sanitizes_sensitive_detail_and_uses_native_rows(self):
        fake_st = _FakeStreamlit()
        entry = SimpleNamespace(
            id=10,
            evento="prompt_guard_block",
            user_email="admin@example.com",
            user_id=1,
            prompt_text=None,
            detalhe="password=abc123 token=reset-secret https://example.com/?reset_password_token=raw",
            criado_em=None,
        )

        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_table([entry])

        rendered = " ".join(str(value) for value in fake_st.writes + fake_st.captions + fake_st.warnings)
        table_rendered = str(_dataframe_records(fake_st.dataframes[0][0])) if fake_st.dataframes else ""
        rendered = f"{rendered} {table_rendered}"
        self.assertIn("Prompt bloqueado", rendered)
        self.assertIn("Bloqueado", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("reset-secret", rendered)
        self.assertNotIn("reset_password_token=raw", rendered)
        self.assertEqual(fake_st.markdowns, [])
        self.assertTrue(any(label == "Ver detalhes" for label, _ in fake_st.buttons))

    def test_clicking_audit_row_stores_snapshot_for_detail_modal(self):
        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("audit-open-selected-detail")
        entry = SimpleNamespace(
            id=10,
            evento="login",
            user_email="admin@example.com",
            user_id=1,
            prompt_text=None,
            detalhe="ok",
            criado_em=None,
        )

        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_table([entry])

        self.assertTrue(fake_st.rerun_called)
        self.assertIn(admin_page.AUDIT_SELECTED_EVENT_KEY, fake_st.session_state)
        self.assertEqual(fake_st.session_state[admin_page.AUDIT_SELECTED_EVENT_KEY]["Evento"], "Login realizado")

    def test_audit_table_empty_state_is_friendly(self):
        fake_st = _FakeStreamlit()

        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_table([])

        self.assertEqual(fake_st.infos[-1], "Nenhum evento encontrado com os filtros selecionados.")

    def test_audit_table_truncates_long_details(self):
        fake_st = _FakeStreamlit()
        long_detail = "x" * 140
        entry = SimpleNamespace(
            evento="login",
            user_email="admin@example.com",
            prompt_text=None,
            detalhe=long_detail,
            criado_em=None,
        )

        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_table([entry])

        rendered = " ".join(str(value) for value in fake_st.writes + fake_st.captions)
        if fake_st.dataframes:
            rendered = f"{rendered} {_dataframe_records(fake_st.dataframes[0][0])}"
        self.assertNotIn(long_detail, rendered)
        self.assertIn("...", rendered)

    def test_filters_do_not_crash_with_empty_logs(self):
        filtered = admin_page._filter_audit_entries(
            [],
            event_type="Todos",
            user_search="ana",
            status="Todos",
            only_failures=False,
            only_blocked=False,
        )

        self.assertEqual(filtered, [])

    def test_filtered_results_match_event_user_status_and_date(self):
        entries = [
            SimpleNamespace(
                evento="login",
                user_email="ana@example.com",
                user_id=1,
                detalhe="ok",
                criado_em=datetime(2026, 6, 1, 10, 0),
            ),
            SimpleNamespace(
                evento="prompt_guard_block",
                user_email="bia@example.com",
                user_id=2,
                detalhe="bloqueado",
                criado_em=datetime(2026, 6, 2, 10, 0),
            ),
            SimpleNamespace(
                evento="login",
                user_email="caio@example.com",
                user_id=3,
                detalhe="failed login",
                criado_em=datetime(2026, 6, 3, 10, 0),
            ),
        ]

        blocked = admin_page._filter_audit_entries(entries, only_blocked=True)
        failures = admin_page._filter_audit_entries(entries, status="failure")
        ana = admin_page._filter_audit_entries(entries, user_search="ana")
        recent_logins = admin_page._filter_audit_entries(
            entries,
            event_type="login",
            start_date=datetime(2026, 6, 3).date(),
        )

        self.assertEqual([entry.user_email for entry in blocked], ["bia@example.com"])
        self.assertEqual([entry.user_email for entry in failures], ["caio@example.com"])
        self.assertEqual([entry.user_email for entry in ana], ["ana@example.com"])
        self.assertEqual([entry.user_email for entry in recent_logins], ["caio@example.com"])

    def test_category_and_summary_filters_match_figma_controls(self):
        entries = [
            SimpleNamespace(evento="login_success", user_email="ana@example.com", detalhe="ok", criado_em=None),
            SimpleNamespace(evento="account_created", user_email="bia@example.com", detalhe="ok", criado_em=None),
            SimpleNamespace(evento="prompt_guard_block", user_email="caio@example.com", detalhe="bloqueado", criado_em=None),
            SimpleNamespace(evento="login_failure", user_email="duda@example.com", detalhe="failed login", criado_em=None),
        ]

        logins = admin_page._filter_audit_entries(entries, event_type="Login")
        accounts = admin_page._filter_audit_entries(entries, event_type="Conta")
        blocked = admin_page._apply_summary_filter(entries, admin_page.AUDIT_SUMMARY_FILTER_BLOCKED)
        failures = admin_page._apply_summary_filter(entries, admin_page.AUDIT_SUMMARY_FILTER_FAILURES)

        self.assertEqual([entry.user_email for entry in logins], ["ana@example.com", "duda@example.com"])
        self.assertEqual([entry.user_email for entry in accounts], ["bia@example.com"])
        self.assertEqual([entry.user_email for entry in blocked], ["caio@example.com"])
        self.assertEqual([entry.user_email for entry in failures], ["duda@example.com"])

    def test_audit_sanitizer_hides_raw_database_errors(self):
        text = admin_page._sanitize_audit_text(
            "OperationalError: postgresql://user:password@host/db Traceback details"
        )

        self.assertEqual(text, "Erro tecnico registrado com seguranca.")
        self.assertNotIn("postgresql://", text)
        self.assertNotIn("Traceback", text)

    def test_render_admin_page_authorized_loads_summary_filters_and_table(self):
        fake_st = _FakeStreamlit()
        user = {"id": 1, "nome": "Heloisa", "email": "admin@example.com", "role": "admin", "can_view_audit": True}
        entries = [
            SimpleNamespace(
                id=1,
                evento="login_success",
                user_email="admin@example.com",
                user_id=1,
                prompt_text=None,
                detalhe="ok",
                status="success",
                criado_em=datetime(2026, 6, 29, 10, 0),
            ),
            SimpleNamespace(
                id=2,
                evento="prompt_guard_block",
                user_email="user@example.com",
                user_id=2,
                prompt_text="prompt sensivel token=abc",
                detalhe="bloqueado",
                status="blocked",
                criado_em=datetime(2026, 6, 29, 11, 0),
            ),
        ]
        audit_service = SimpleNamespace(get_recent_logs=lambda limit: entries)

        with (
            patch.object(admin_page, "st", fake_st),
            patch.object(admin_page, "get_authenticated_user", return_value=user),
            patch.object(admin_page, "_get_audit_service", return_value=audit_service),
        ):
            admin_page.render_admin_page()

        self.assertIn("Painel de Auditoria", fake_st.texts)
        self.assertEqual(fake_st.metrics[0], ("Total de eventos", 2))
        self.assertTrue(fake_st.dataframes)
        table_rendered = str(_dataframe_records(fake_st.dataframes[0][0]))
        self.assertIn("Login realizado", table_rendered)
        self.assertIn("Prompt bloqueado", table_rendered)
        self.assertNotIn("token=abc", table_rendered)

    def test_render_admin_page_blocks_unauthorized_user(self):
        fake_st = _FakeStreamlit()
        user = {"id": 2, "nome": "User", "email": "user@example.com", "role": "user", "can_view_audit": False}

        with (
            patch.object(admin_page, "st", fake_st),
            patch.object(admin_page, "get_authenticated_user", return_value=user),
        ):
            with self.assertRaises(RuntimeError):
                admin_page.render_admin_page()

        self.assertEqual(fake_st.errors[-1], "Acesso restrito. Esta area e exclusiva para administradores autorizados.")

    def test_render_admin_page_super_admin_user_management_does_not_crash(self):
        fake_st = _FakeStreamlit()
        user = {"id": 1, "nome": "Root", "email": "root@example.com", "role": "super_admin", "can_view_audit": True}
        managed_users = [
            SimpleNamespace(id=1, nome="Root", email="root@example.com", role="super_admin", can_view_audit=True),
            SimpleNamespace(id=2, nome="Ana", email="ana@example.com", role="user", can_view_audit=False),
        ]
        user_service = SimpleNamespace(get_all_users=lambda: managed_users)
        audit_service = SimpleNamespace(get_recent_logs=lambda limit: [])

        with (
            patch.object(admin_page, "st", fake_st),
            patch.object(admin_page, "get_authenticated_user", return_value=user),
            patch.object(admin_page, "_get_user_service", return_value=user_service),
            patch.object(admin_page, "_get_audit_service", return_value=audit_service),
        ):
            admin_page.render_admin_page()

        self.assertIn("Gestao de Usuarios", fake_st.subheaders)
        self.assertIn("Nenhum evento encontrado com os filtros selecionados.", fake_st.infos)

    def test_admin_helpers_cover_labels_dates_limits_and_buttons(self):
        self.assertEqual(admin_page._safe_admin_error_summary(RuntimeError("boom")), "RuntimeError")
        self.assertEqual(admin_page._truncate_display("abcdef", max_len=4), "abc...")
        self.assertEqual(admin_page._audit_status("admin_access_denied"), "blocked")
        self.assertEqual(admin_page._audit_status("login", "failed"), "failure")
        self.assertEqual(admin_page._audit_status("login"), "success")
        self.assertEqual(admin_page._normalize_status("misterio"), "info")

        entry = SimpleNamespace(evento="login_failure", detalhe="falha", status="sucesso", criado_em="2026-06-29T10:00:00")
        self.assertEqual(admin_page._entry_status(entry), "success")
        self.assertEqual(admin_page._coerce_entry_date(entry.criado_em).isoformat(), "2026-06-29")
        self.assertIsNone(admin_page._coerce_entry_date("data-invalida"))
        self.assertEqual(admin_page._available_event_types([entry, SimpleNamespace(evento="account_created")]), ["account_created", "login_failure"])
        self.assertEqual(admin_page._event_category("logout"), "Login")
        self.assertEqual(admin_page._event_category("role_changed"), "Administracao")
        self.assertEqual(admin_page._event_category("email_change_requested"), "Conta")
        self.assertTrue(admin_page._matches_event_filter(entry, "login_failure"))
        self.assertFalse(admin_page._matches_event_filter(entry, "account_created"))
        self.assertEqual(admin_page._limit_audit_entries([1, 2, 3], 999), [1, 2, 3])
        self.assertEqual(admin_page._event_label(SimpleNamespace(evento="login", detalhe="failed", status="failure")), "Falha no login")

        class WeirdDate:
            def strftime(self, fmt):
                raise RuntimeError("bad")

            def __str__(self):
                return "weird-date"

        self.assertEqual(admin_page._format_dt(WeirdDate()), "weird-date")
        user_obj = SimpleNamespace(nome="Ana Maria", email="ana@example.com", role="admin")
        self.assertEqual(admin_page._user_value(user_obj, "email"), "ana@example.com")
        self.assertEqual(admin_page._user_value({"email": "root@example.com"}, "email"), "root@example.com")
        self.assertEqual(admin_page._user_value(None, "email", "x"), "x")
        self.assertEqual(admin_page._user_initials(user_obj), "AM")
        self.assertEqual(admin_page._user_initials({"email": "root@example.com"}), "RO")

        with patch.object(admin_page.st, "button", side_effect=[TypeError("icon"), True]) as button:
            self.assertTrue(admin_page._safe_button("Atualizar", icon="refresh"))
        self.assertEqual(button.call_count, 2)

    def test_status_and_event_badges_use_native_components_with_fallbacks(self):
        fake_st = _FakeStreamlit()
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_status_badge("success")
            admin_page._render_status_badge("failure")
            admin_page._render_status_badge("blocked")
            admin_page._render_status_badge("info")
            admin_page._render_event_badge("Login realizado")

        self.assertEqual([label for label, _ in fake_st.badges[:4]], ["Sucesso", "Falha", "Bloqueado", "Informativo"])
        self.assertEqual(fake_st.badges[-1][0], "Login realizado")

        fake_st = _FakeStreamlit()
        fake_st.badge = MagicMock(side_effect=RuntimeError("badge unavailable"))
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_status_badge("success")
            admin_page._render_status_badge("failure")
            admin_page._render_status_badge("blocked")
            admin_page._render_status_badge("info")
            admin_page._render_event_badge("Conta criada")

        self.assertEqual(fake_st.successes, ["Sucesso"])
        self.assertEqual(fake_st.errors, ["Falha"])
        self.assertEqual(fake_st.warnings, ["Bloqueado"])
        self.assertEqual(fake_st.infos, ["Informativo"])
        self.assertIn("Conta criada", fake_st.writes[-1])

    def test_filter_buttons_refresh_clear_and_apply_rerun_safely(self):
        for key in ["audit-refresh", "audit-clear-filters", "audit-apply-filters"]:
            fake_st = _FakeStreamlit()
            fake_st.clicked_keys.add(key)
            fake_st.session_state.update(
                {
                    "audit-filter-event-type": "Login",
                    "audit-filter-user-search": "ana",
                    "audit-filter-status": "failure",
                    "audit-result-limit": 20,
                    admin_page.AUDIT_SUMMARY_FILTER_KEY: admin_page.AUDIT_SUMMARY_FILTER_FAILURES,
                }
            )
            with self.subTest(key=key):
                with patch.object(admin_page, "st", fake_st):
                    filters = admin_page._render_audit_filters([])
                self.assertTrue(fake_st.rerun_called)
                self.assertIn("limit", filters)
                if key == "audit-clear-filters":
                    self.assertNotIn("audit-filter-event-type", fake_st.session_state)

    def test_selected_audit_event_dialog_uses_native_dialog_and_close(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state[admin_page.AUDIT_SELECTED_EVENT_KEY] = {
            "Evento": "Login realizado",
            "StatusKey": "success",
            "Data/Hora": "29/06/2026 10:00:00",
            "E-mail": "ana@example.com",
            "Prompt": "-",
            "Detalhe": "ok",
            "Metadados": "ID do evento: 1",
        }
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_selected_audit_event_dialog()

        self.assertEqual(fake_st.dialogs[0][0], "Detalhes do evento")
        self.assertIn("Login realizado", fake_st.writes)
        self.assertIn("ok", fake_st.writes)

        fake_st.clicked_keys.add("audit-detail-close")
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_audit_event_dialog_body(fake_st.session_state[admin_page.AUDIT_SELECTED_EVENT_KEY])
        self.assertNotIn(admin_page.AUDIT_SELECTED_EVENT_KEY, fake_st.session_state)
        self.assertTrue(fake_st.rerun_called)

    def test_user_management_error_empty_and_action_paths(self):
        admin = {"id": 1, "email": "root@example.com"}

        fake_st = _FakeStreamlit()
        service = SimpleNamespace(get_all_users=lambda: (_ for _ in ()).throw(RuntimeError("db")))
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_user_management(admin, service)
        self.assertEqual(fake_st.errors[-1], "Nao foi possivel carregar os usuarios agora.")

        fake_st = _FakeStreamlit()
        service = SimpleNamespace(get_all_users=lambda: [])
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_user_management(admin, service)
        self.assertEqual(fake_st.infos[-1], "Nenhum usuario encontrado.")

        managed = [
            SimpleNamespace(id=1, nome="Root", email="root@example.com", role="super_admin", can_view_audit=True),
            SimpleNamespace(id=2, nome="Ana", email="ana@example.com", role="user", can_view_audit=False),
        ]
        fake_st = _FakeStreamlit()
        fake_st.session_state["role_select_2"] = "admin"
        fake_st.clicked_keys.update({"save_role_2", "grant_audit_2", "delete_user_2"})
        service = SimpleNamespace(
            get_all_users=lambda: managed,
            set_role=MagicMock(),
            set_audit_access=MagicMock(),
            soft_delete_user=MagicMock(),
        )
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_user_management(admin, service)

        service.set_role.assert_called_once()
        service.set_audit_access.assert_called_once_with(2, True, acting_admin_id=1, acting_admin_email="root@example.com")
        self.assertTrue(fake_st.session_state["confirm_delete_2"])

        fake_st = _FakeStreamlit()
        fake_st.session_state["confirm_delete_2"] = True
        fake_st.clicked_keys.add("confirm_yes_2")
        service.soft_delete_user.reset_mock()
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_user_management(admin, service)
        service.soft_delete_user.assert_called_once_with(2)

        managed[1] = SimpleNamespace(id=2, nome="Ana", email="ana@example.com", role="user", can_view_audit=True)
        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("revoke_audit_2")
        service.set_audit_access.reset_mock()
        with patch.object(admin_page, "st", fake_st):
            admin_page._render_user_management(admin, service)
        service.set_audit_access.assert_called_once_with(2, False, acting_admin_id=1, acting_admin_email="root@example.com")

    def test_render_admin_page_handles_audit_loading_failure_safely(self):
        fake_st = _FakeStreamlit()
        user = {"id": 1, "nome": "Heloisa", "email": "admin@example.com", "role": "admin", "can_view_audit": True}
        audit_service = SimpleNamespace(get_recent_logs=lambda limit: (_ for _ in ()).throw(RuntimeError("db")))

        with (
            patch.object(admin_page, "st", fake_st),
            patch.object(admin_page, "get_authenticated_user", return_value=user),
            patch.object(admin_page, "_get_audit_service", return_value=audit_service),
        ):
            admin_page.render_admin_page()

        self.assertEqual(fake_st.errors[-1], "Nao foi possivel carregar os logs agora. Tente novamente mais tarde.")


if __name__ == "__main__":
    unittest.main()
