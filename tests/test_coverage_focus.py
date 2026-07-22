import importlib
import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

import app_ai_chat as app
from src.ai import query_logger, read_only_datasus
from src.auth import roles, security


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _SessionState()
        self.query_params = {}
        self.markdowns = []
        self.successes = []
        self.errors = []
        self.warnings = []
        self.infos = []
        self.forms = []
        self.text_value = ""
        self.submitted = False
        self.rerun_called = False

    def markdown(self, value, unsafe_allow_html=False):
        self.markdowns.append((value, unsafe_allow_html))

    def success(self, value):
        self.successes.append(value)

    def error(self, value):
        self.errors.append(value)

    def warning(self, value):
        self.warnings.append(value)

    def info(self, value):
        self.infos.append(value)

    def set_page_config(self, **kwargs):
        self.page_config = kwargs

    def form(self, key, clear_on_submit=False):
        self.forms.append((key, clear_on_submit))
        return self

    def columns(self, count, **kwargs):
        total = count if isinstance(count, int) else len(count)
        return [self for _ in range(total)]

    def text_input(self, *args, **kwargs):
        return self.text_value

    def form_submit_button(self, *args, **kwargs):
        return self.submitted

    def button(self, *args, **kwargs):
        return False

    def rerun(self):
        self.rerun_called = True
        raise RuntimeError("rerun")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestAppFormattingAndExternalIntegration(unittest.TestCase):
    def test_assistant_content_formats_safe_structured_outputs(self):
        with patch.object(app, "_get_pandas_module", return_value=pd):
            self.assertIn("assistant-result", app._render_assistant_content("123,45"))
            self.assertIn("assistant-table", app._render_assistant_content('[{"Cidade": "Mamanguape", "Total": 3}]'))
            self.assertIn("<ul", app._render_assistant_content('["um", "dois"]'))
            self.assertIn("assistant-table", app._render_assistant_content("| A | B |\n|---|---|\n| x | 1 |"))
            self.assertIn("assistant-table", app._render_assistant_content("- A: 1\n- B: 2"))
            self.assertIn("<ol", app._render_assistant_content("1. Primeiro\n2. Segundo"))

    def test_friendly_response_replaces_unsafe_provider_details(self):
        unsafe = "Traceback with postgresql://user:password@host/db and token=abc"

        friendly = app._friendly_response(unsafe)

        self.assertEqual(friendly, app.GENERIC_ERROR_MESSAGE)
        self.assertNotIn("postgresql://", friendly)
        self.assertNotIn("token=abc", friendly)

    def test_password_reset_query_param_opens_reset_panel_without_showing_token(self):
        fake_st = _FakeStreamlit()
        fake_st.query_params["reset_password_token"] = ["raw-token"]

        with patch.object(app, "st", fake_st), patch.object(app, "set_auth_panel") as set_panel:
            app._handle_password_reset_query_param()

        self.assertEqual(fake_st.session_state["password_reset_token"], "raw-token")
        set_panel.assert_called_once_with("reset_password", redirect_on_close=app.DEFAULT_PAGE)
        self.assertNotIn("reset_password_token", fake_st.query_params)

    def test_email_verification_query_param_stores_safe_feedback(self):
        fake_st = _FakeStreamlit()
        fake_st.query_params["verify_email_token"] = "raw-token"
        service = SimpleNamespace(
            verify_email_token=MagicMock(return_value=SimpleNamespace(success=True, message="E-mail verificado."))
        )

        with patch.object(app, "st", fake_st), patch.object(app, "_get_email_verification_service", return_value=service):
            app._handle_email_verification_query_param()

        self.assertEqual(fake_st.session_state["email_verification_feedback"]["message"], "E-mail verificado.")
        self.assertTrue(fake_st.session_state["email_verification_feedback"]["success"])
        self.assertNotIn("verify_email_token", fake_st.query_params)

    def test_google_oauth_callback_success_logs_in_without_exposing_tokens(self):
        fake_st = _FakeStreamlit()
        fake_st.query_params.update({"code": "auth-code", "state": "state-ok", "scope": "openid"})
        fake_st.session_state[app.GOOGLE_OAUTH_TARGET_PAGE_KEY] = app.CHAT_PAGE
        identity = SimpleNamespace(
            sub="google-sub",
            email="ana@example.com",
            email_verified=True,
            name="Ana",
            picture=None,
        )
        user = {"id": 1, "email": "ana@example.com", "nome": "Ana"}
        oauth_service = SimpleNamespace(exchange_code_for_identity=MagicMock(return_value=identity))
        auth_service = SimpleNamespace(authenticate_google_identity=MagicMock(return_value=user))

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "validate_oauth_state", return_value=True),
            patch.object(app, "_get_google_oauth_service", return_value=oauth_service),
            patch.object(app, "_get_auth_user_service", return_value=auth_service),
            patch.object(app, "login_session") as login_session,
            patch.object(app, "close_auth_modal") as close_modal,
            patch.object(app, "queue_toast") as queue_toast,
            patch.object(app, "set_current_page") as set_page,
            patch.object(app, "clear_oauth_state") as clear_state,
        ):
            app._handle_google_oauth_query_param()

        login_session.assert_called_once_with(fake_st.session_state, user)
        close_modal.assert_called_once_with(redirect=False)
        queue_toast.assert_called_once()
        set_page.assert_called_once_with(app.CHAT_PAGE)
        clear_state.assert_called_once()
        self.assertEqual(fake_st.session_state["google_oauth_feedback"]["message"], "Login com Google realizado com sucesso.")
        self.assertNotIn("code", fake_st.query_params)
        self.assertNotIn("state", fake_st.query_params)

    def test_google_oauth_callback_invalid_state_sets_safe_error(self):
        fake_st = _FakeStreamlit()
        fake_st.query_params.update({"code": "auth-code", "state": "bad-state"})

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "validate_oauth_state", return_value=False),
            patch.object(app, "clear_oauth_state") as clear_state,
        ):
            app._handle_google_oauth_query_param()

        clear_state.assert_called_once()
        self.assertEqual(
            fake_st.session_state["google_oauth_feedback"]["message"],
            app.GOOGLE_OAUTH_INVALID_STATE_MESSAGE,
        )

    def test_chat_email_verification_required_paths_are_safe(self):
        fake_st = _FakeStreamlit()

        with patch.object(app, "st", fake_st), patch.object(app, "is_email_verification_required", return_value=False):
            self.assertTrue(app._can_use_chat_with_email_verification())

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "is_email_verification_required", return_value=True),
            patch.object(app, "get_authenticated_user", return_value=None),
        ):
            self.assertFalse(app._can_use_chat_with_email_verification())

        service = SimpleNamespace(is_email_verified=MagicMock(side_effect=RuntimeError("db down")))
        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "is_email_verification_required", return_value=True),
            patch.object(app, "get_authenticated_user", return_value={"id": 5}),
            patch.object(app, "_get_email_verification_service", return_value=service),
        ):
            self.assertFalse(app._can_use_chat_with_email_verification())

    def test_chat_history_helpers_create_reuse_and_fail_safely(self):
        fake_st = _FakeStreamlit()
        created_session = SimpleNamespace(id=77)
        service = SimpleNamespace(
            get_chat_session=MagicMock(return_value=created_session),
            get_or_create_active_chat_session=MagicMock(return_value=created_session),
            add_chat_message=MagicMock(),
        )

        fake_st.session_state["chat_history_session_id"] = 77
        with patch.object(app, "st", fake_st), patch.object(app, "_get_chat_history_service", return_value=service):
            self.assertEqual(app._get_or_create_chat_history_session_id(1, "Prompt"), 77)
            app._persist_chat_history_message(user_id=1, role="user", content="Oi", status="ok", prompt_for_title="Prompt")

        service.add_chat_message.assert_called_once_with(77, 1, "user", "Oi", status="ok")

        broken_service = SimpleNamespace(get_chat_session=MagicMock(side_effect=RuntimeError("db")))
        with patch.object(app, "st", fake_st), patch.object(app, "_get_chat_history_service", return_value=broken_service):
            self.assertIsNone(app._get_or_create_chat_history_session_id(1, "Prompt"))

    def test_queue_prompt_blocks_anonymous_duplicate_and_unverified_cases(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state["pending_prompt"] = None

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=False),
            patch.object(app, "open_auth_modal") as open_modal,
        ):
            app._queue_prompt("Total")

        open_modal.assert_called_once()
        self.assertIsNone(fake_st.session_state["pending_prompt"])

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=False),
        ):
            app._queue_prompt("Total")
        self.assertIsNone(fake_st.session_state["pending_prompt"])

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=True),
        ):
            app._queue_prompt("Total")
            app._queue_prompt("Total")
        self.assertEqual(fake_st.session_state["pending_prompt"], "Total")

    def test_process_pending_prompt_blocked_before_provider_call(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state["pending_prompt"] = "Total"

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=False),
            patch.object(app, "open_auth_modal") as open_modal,
        ):
            self.assertFalse(app._process_pending_prompt())

        self.assertIsNone(fake_st.session_state["pending_prompt"])
        open_modal.assert_called_once()

        fake_st.session_state["pending_prompt"] = "Total"
        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=False),
        ):
            self.assertFalse(app._process_pending_prompt())
        self.assertIsNone(fake_st.session_state["pending_prompt"])

    def test_authorized_page_logs_denied_admin_access_safely(self):
        fake_st = _FakeStreamlit()
        user = {"id": 1, "email": "user@example.com", "role": "user", "can_view_audit": False}

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "get_authenticated_user", return_value=user),
            patch.object(app, "_log_audit_event") as audit,
            patch.object(app, "set_current_page") as set_page,
        ):
            resolved = app._resolve_authorized_page(app.ADMIN_PAGE)

        self.assertEqual(resolved, app.DEFAULT_PAGE)
        audit.assert_called_once()
        set_page.assert_called_once_with(app.DEFAULT_PAGE)
        self.assertEqual(fake_st.session_state["admin_access_feedback"], app.ADMIN_ACCESS_DENIED_MESSAGE)

    def test_feedback_renderers_pop_messages(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state["email_verification_feedback"] = {"message": "ok", "success": True}
        fake_st.session_state["google_oauth_feedback"] = {"message": "erro", "success": False}
        fake_st.session_state["admin_access_feedback"] = "sem permissao"

        with patch.object(app, "st", fake_st):
            app._render_email_verification_feedback()
            app._render_google_oauth_feedback()
            app._render_admin_access_feedback()

        self.assertEqual(fake_st.successes, ["ok"])
        self.assertEqual(fake_st.errors, ["erro"])
        self.assertEqual(fake_st.warnings, ["sem permissao"])
        self.assertNotIn("email_verification_feedback", fake_st.session_state)

    def test_process_pending_prompt_uses_mocked_llm_and_persists_messages_once(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state.update(
            {
                "pending_prompt": "Total por municipio",
                "messages": [],
                "auth_user": {"id": 7, "email": "ana@example.com"},
            }
        )
        runner = MagicMock(return_value="Resposta segura")

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "get_authenticated_user", return_value={"id": 7, "email": "ana@example.com"}),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=True),
            patch.object(app, "_persist_chat_history_message") as persist,
            patch.object(app, "_render_chat_history"),
            patch.object(app, "_render_input_form"),
            patch.object(app, "_get_datasus_question_runner", return_value=runner),
        ):
            with self.assertRaises(RuntimeError):
                app._process_pending_prompt()

        self.assertIsNone(fake_st.session_state["pending_prompt"])
        self.assertEqual(
            fake_st.session_state["messages"],
            [
                {"role": "user", "content": "Total por municipio"},
                {"role": "assistant", "content": "Resposta segura"},
            ],
        )
        self.assertEqual(persist.call_count, 2)
        runner.assert_called_once()

    def test_process_pending_prompt_provider_failure_returns_safe_message_and_audits(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state.update(
            {
                "pending_prompt": "Pergunta dificil",
                "messages": [],
                "auth_user": {"id": 7, "email": "ana@example.com"},
            }
        )

        def failing_runner(*args, **kwargs):
            raise RuntimeError("provider down")

        with (
            patch.object(app, "st", fake_st),
            patch.object(app, "can_access_chat", return_value=True),
            patch.object(app, "get_authenticated_user", return_value={"id": 7, "email": "ana@example.com"}),
            patch.object(app, "_can_use_chat_with_email_verification", return_value=True),
            patch.object(app, "_persist_chat_history_message"),
            patch.object(app, "_render_chat_history"),
            patch.object(app, "_render_input_form"),
            patch.object(app, "_get_datasus_question_runner", return_value=failing_runner),
            patch.object(app, "_log_audit_event") as audit,
        ):
            with self.assertRaises(RuntimeError):
                app._process_pending_prompt()

        self.assertEqual(fake_st.session_state["messages"][-1]["content"], app.GENERIC_ERROR_MESSAGE)
        audit.assert_called_once()
        self.assertEqual(audit.call_args.args[0], "chat_processing_error")

    def test_app_cached_service_factories_and_audit_wrapper_are_mocked(self):
        with (
            patch.object(app.EmailVerificationService, "from_environment", return_value="email-verification"),
            patch.object(app.UserService, "from_environment", return_value="auth-user"),
            patch.object(app.GoogleOAuthService, "from_environment", return_value="google-oauth"),
            patch.object(app.ChatHistoryService, "from_environment", return_value="chat-history"),
        ):
            self.assertIsNotNone(app._get_pandas_module.__wrapped__())
            self.assertTrue(callable(app._get_datasus_question_runner.__wrapped__()))
            self.assertEqual(app._get_email_verification_service.__wrapped__(), "email-verification")
            self.assertEqual(app._get_auth_user_service.__wrapped__(), "auth-user")
            self.assertEqual(app._get_google_oauth_service.__wrapped__(), "google-oauth")
            self.assertEqual(app._get_chat_history_service.__wrapped__(), "chat-history")

        fake_auth_service = SimpleNamespace(engine="engine")
        with (
            patch.object(app, "_get_auth_user_service", return_value=fake_auth_service),
            patch("src.audit.audit_log_service.log_audit_event_safely") as log_event,
        ):
            app._log_audit_event("login", user_id=1, user_email="ana@example.com")
        log_event.assert_called_once_with("engine", "login", user_id=1, user_email="ana@example.com")

        with (
            patch.object(app, "_get_auth_user_service", side_effect=RuntimeError("db")),
            self.assertLogs("app_ai_chat", level="WARNING") as logs,
        ):
            app._log_audit_event("login", user_id=1)
        self.assertIn("audit_log_app", "\n".join(logs.output))


class TestEtlHelpers(unittest.TestCase):
    def _import_extract_with_stubs(self):
        sys.modules.pop("src.extract", None)
        with patch.dict(sys.modules, {"pysus": SimpleNamespace(SIA=object)}):
            return importlib.import_module("src.extract")

    def _import_load_with_stubs(self):
        sys.modules.pop("src.load", None)
        fake_dotenv = SimpleNamespace(load_dotenv=lambda *args, **kwargs: None)
        with (
            patch.dict(sys.modules, {"dotenv": fake_dotenv}),
            patch("sqlalchemy.create_engine", return_value=MagicMock()),
        ):
            return importlib.import_module("src.load")

    def test_extract_data_downloads_only_expected_month(self):
        extract = self._import_extract_with_stubs()

        class FakeFile:
            name = "PAPB2605.dbc"

        class FakeFrame:
            def __init__(self):
                self.to_parquet = MagicMock()

            def __len__(self):
                return 2

        class FakeDownloaded:
            def to_dataframe(self):
                return FakeFrame()

        fake_sia = SimpleNamespace(
            get_files=MagicMock(return_value=[FakeFile()]),
            download=MagicMock(return_value=FakeDownloaded()),
        )

        with patch.object(extract, "get_target_period", return_value=(2026, 5)):
            output = extract.extract_data(fake_sia)

        self.assertEqual(output, "data/sia_datasus.parquet")
        fake_sia.download.assert_called_once()

    def test_extract_data_handles_empty_invalid_and_unexpected_month(self):
        extract = self._import_extract_with_stubs()

        empty_sia = SimpleNamespace(get_files=MagicMock(return_value=[]))
        invalid_sia = SimpleNamespace(get_files=MagicMock(return_value=[SimpleNamespace(name="PAPB26XX.dbc")]))
        old_sia = SimpleNamespace(get_files=MagicMock(return_value=[SimpleNamespace(name="PAPB2604.dbc")]))

        with patch.object(extract, "get_target_period", return_value=(2026, 5)):
            self.assertIsNone(extract.extract_data(empty_sia))
            self.assertIsNone(extract.extract_data(invalid_sia))
            self.assertIsNone(extract.extract_data(old_sia))

    def test_transform_pipeline_filters_and_casts_datasus_rows(self):
        import src.transform as transform

        df = pd.DataFrame(
            [
                {
                    "frequencia": "2",
                    "quantidade_apresentada": "3",
                    "idade": "45",
                    "valor_aprovado": "10.5",
                    "valor_apresentado": "11.5",
                    "data": "202605",
                    "cod_municipio_atendido": "250890",
                    "cod_unidade": "2597349",
                },
                {
                    "frequencia": "1",
                    "quantidade_apresentada": "1",
                    "idade": "30",
                    "valor_aprovado": "1.0",
                    "valor_apresentado": "1.0",
                    "data": "202605",
                    "cod_municipio_atendido": "999999",
                    "cod_unidade": "0000000",
                },
            ]
        )

        filtered = transform.transform_filter_units(transform.transform_filter_city(df))
        fixed = transform.transform_fix_types(filtered)

        self.assertEqual(len(fixed), 1)
        self.assertEqual(str(fixed.iloc[0]["data"].date()), "2026-05-01")
        self.assertEqual(fixed.iloc[0]["frequencia"], 2)
        self.assertEqual(fixed.iloc[0]["valor_aprovado"], 10.5)

    def test_transform_datasus_runs_ordered_pipeline(self):
        import src.transform as transform

        calls = []

        with (
            patch.object(transform, "transform_remove_columns", side_effect=lambda path: calls.append("remove") or "a"),
            patch.object(transform, "transform_rename_columns", side_effect=lambda df: calls.append(("rename", df)) or "b"),
            patch.object(transform, "transform_filter_city", side_effect=lambda df: calls.append(("city", df)) or "c"),
            patch.object(transform, "transform_filter_units", side_effect=lambda df: calls.append(("units", df)) or "d"),
            patch.object(transform, "transform_fix_types", side_effect=lambda df: calls.append(("types", df)) or "final"),
        ):
            result = transform.transform_datasus("input.parquet")

        self.assertEqual(result, "final")
        self.assertEqual(calls, ["remove", ("rename", "a"), ("city", "b"), ("units", "c"), ("types", "d")])

    def test_load_helpers_use_mocked_database_objects(self):
        load = self._import_load_with_stubs()

        fake_engine = MagicMock()
        fake_df = MagicMock()
        with (
            patch.object(load, "engine", fake_engine),
            patch.object(load.pd, "read_sql", return_value=pd.DataFrame({"id": [1]})) as read_sql,
        ):
            load.load_data_sus("data_sus", fake_df)

        fake_df.to_sql.assert_called_once_with(name="data_sus", con=fake_engine, if_exists="append", index=False)
        read_sql.assert_called_once()

    def test_check_data_exists_success_false_and_safe_exception(self):
        load = self._import_load_with_stubs()

        class FakeResult:
            def __init__(self, row):
                self.row = row

            def fetchone(self):
                return self.row

        class FakeConn:
            def __init__(self, row=None, error=None):
                self.row = row
                self.error = error

            def execute(self, *args, **kwargs):
                if self.error:
                    raise self.error
                return FakeResult(self.row)

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        class FakeEngine:
            def __init__(self, row=None, error=None):
                self.row = row
                self.error = error

            def connect(self):
                return FakeConn(self.row, self.error)

        with patch.object(load, "engine", FakeEngine(row=(1,))):
            self.assertTrue(load.check_data_exists("data_sus", 2026, 5))
        with patch.object(load, "engine", FakeEngine(row=None)):
            self.assertFalse(load.check_data_exists("data_sus", 2026, 5))
        with patch.object(load, "engine", FakeEngine(error=RuntimeError("db down"))):
            self.assertFalse(load.check_data_exists("data_sus", 2026, 5))


class TestSmallSecurityAndConfigHelpers(unittest.TestCase):
    def test_readonly_datasus_requires_ai_env_and_builds_safe_engine(self):
        with patch.dict(os.environ, {"ENVIRONMENT": "test"}, clear=True):
            with self.assertRaises(RuntimeError):
                read_only_datasus.get_readonly_engine()

        env = {
            "ENVIRONMENT": "test",
            "AI_DB_USER": "ia_user",
            "AI_DB_PASSWORD": "p@ ss",
            "AI_DB_HOST": "db.example.com",
            "AI_DB_PORT": "5432",
            "AI_DB_NAME": "analytics",
        }
        with patch.dict(os.environ, env, clear=True), patch("sqlalchemy.create_engine") as create_engine:
            read_only_datasus.get_readonly_engine()

        url = create_engine.call_args.args[0]
        self.assertIn("ia_user", url)
        self.assertIn("p%40+ss", url)
        self.assertIn("db.example.com:5432", url)
        self.assertIn("sslmode=require", url)
        self.assertEqual(
            create_engine.call_args.kwargs["connect_args"],
            {"options": "-c default_transaction_read_only=on"},
        )

    def test_readonly_datasus_last_available_date_uses_read_only_query(self):
        expected_date = date(2026, 5, 1)

        class FakeResult:
            def mappings(self):
                return self

            def first(self):
                return {"ultima_data": expected_date}

        class FakeConn:
            def execute(self, query):
                self.query = str(query)
                return FakeResult()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

        class FakeEngine:
            def connect(self):
                return FakeConn()

        self.assertEqual(read_only_datasus.get_last_available_date(FakeEngine()), expected_date)

    def test_query_logger_records_metadata_not_prompt_content(self):
        with self.assertLogs("src.ai.query_logger", level="INFO") as logs:
            query_logger.log_ai_question("senha=segredo", "blocked", detail="guard")

        output = "\n".join(logs.output)
        self.assertIn("status=blocked", output)
        self.assertIn("tamanho_prompt=13", output)
        self.assertNotIn("segredo", output)

    def test_roles_support_dicts_objects_and_unknown_display(self):
        self.assertFalse(roles.can_view_audit_log(None))
        self.assertTrue(roles.can_view_audit_log({"role": roles.ROLE_ADMIN}))
        self.assertTrue(roles.can_view_audit_log(SimpleNamespace(role="user", can_view_audit=True)))
        self.assertTrue(roles.is_super_admin(SimpleNamespace(role=roles.ROLE_SUPER_ADMIN)))
        self.assertEqual(roles.role_display_name("custom"), "custom")

    def test_password_hashing_accepts_argon2_and_legacy_pbkdf2(self):
        password = "SenhaSegura123"
        stored = security.hash_password(password)

        self.assertTrue(security.verify_password(password, stored))
        self.assertFalse(security.verify_password("errada", stored))

        legacy = security._pbkdf2_hash(password)
        self.assertTrue(security.verify_password(password, legacy))
        self.assertFalse(security.verify_password("", legacy))
        self.assertFalse(security._pbkdf2_verify(password, "invalid"))


if __name__ == "__main__":
    unittest.main()
