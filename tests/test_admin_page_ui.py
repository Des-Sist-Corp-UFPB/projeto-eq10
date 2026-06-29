from types import SimpleNamespace
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

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

    def container(self, **kwargs):
        return self

    def expander(self, *args, **kwargs):
        return self

    def text(self, value):
        self.texts.append(value)

    def write(self, value):
        self.writes.append(value)

    def date_input(self, label, value=None, **kwargs):
        return value

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


if __name__ == "__main__":
    unittest.main()
