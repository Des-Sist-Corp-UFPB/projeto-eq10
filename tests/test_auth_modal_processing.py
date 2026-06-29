import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.ui import auth_modal


class _FakeSessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _FakeStreamlit:
    def __init__(self):
        self.session_state = _FakeSessionState()
        self.markdowns = []
        self.buttons = []
        self.link_buttons = []
        self.inputs = {}
        self.clicked_keys = set()
        self.form_submitted = False
        self.rerun_called = False

    def markdown(self, body, unsafe_allow_html=False):
        self.markdowns.append((body, unsafe_allow_html))

    def empty(self):
        return self

    def form(self, *args, **kwargs):
        return self

    def spinner(self, *args, **kwargs):
        return self

    def columns(self, count, **kwargs):
        total = count if isinstance(count, int) else len(count)
        return [self for _ in range(total)]

    def text_input(self, label, **kwargs):
        key = kwargs.get("key") or label
        return self.inputs.get(key, self.inputs.get(label, kwargs.get("value", "")))

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs))
        clicked = kwargs.get("key") in self.clicked_keys
        if clicked and kwargs.get("on_click"):
            kwargs["on_click"](*kwargs.get("args", ()))
        return clicked

    def form_submit_button(self, label, **kwargs):
        if self.form_submitted and kwargs.get("on_click"):
            kwargs["on_click"](*kwargs.get("args", ()))
        return self.form_submitted

    def link_button(self, label, url, **kwargs):
        self.link_buttons.append((label, url, kwargs))

    def rerun(self):
        self.rerun_called = True
        raise RuntimeError("rerun")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


class TestAuthModalProcessing(unittest.TestCase):
    def test_clear_auth_processing_state_removes_all_known_flags(self):
        session_state = _FakeSessionState(
            {
                "auth_modal_processing_message": "Entrando...",
                "auth_processing": True,
                "login_processing": True,
                "register_processing": True,
                "forgot_password_processing": True,
                "reset_password_processing": True,
                "email_code_processing": True,
                "google_processing": True,
                "profile_processing": True,
                "email_processing": True,
                "reactivation_processing": True,
                "auth_modal_feedback_message": "erro anterior",
            }
        )

        auth_modal.clear_auth_processing_state(session_state)

        for key in auth_modal.AUTH_MODAL_PROCESSING_STATE_KEYS:
            self.assertNotIn(key, session_state)
        self.assertEqual(session_state["auth_modal_feedback_message"], "erro anterior")

    def test_start_modal_processing_clears_stale_flags_first(self):
        session_state = _FakeSessionState(
            {
                "login_processing": True,
                "google_processing": True,
            }
        )

        with patch.object(auth_modal.st, "session_state", session_state):
            auth_modal._start_modal_processing("Entrando...")

        self.assertEqual(session_state[auth_modal.AUTH_MODAL_PROCESSING_KEY], "Entrando...")
        self.assertNotIn("login_processing", session_state)
        self.assertNotIn("google_processing", session_state)

    def test_finish_modal_action_feedback_clears_processing_before_rerun(self):
        session_state = _FakeSessionState(
            {
                auth_modal.AUTH_MODAL_PROCESSING_KEY: "Entrando...",
                "login_processing": True,
            }
        )

        with (
            patch.object(auth_modal.st, "session_state", session_state),
            patch.object(auth_modal.st, "rerun", side_effect=RuntimeError("rerun")) as rerun,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._finish_modal_action_feedback("Erro de login.", "error")

        rerun.assert_called_once()
        self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, session_state)
        self.assertNotIn("login_processing", session_state)
        self.assertEqual(session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Erro de login.")
        self.assertEqual(session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")

    def test_modal_state_helpers_open_switch_close_and_profile_back(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state.update(
            {
                "auth_modal_processing_message": "Entrando...",
                "auth-change-name-input": "stale",
                "pending_email_change_id": 10,
            }
        )

        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "set_current_page") as set_page:
            auth_modal.open_auth_modal("register", redirect_on_close="Estatisticas", target_page_on_success="Chat IA")
            self.assertEqual(fake_st.session_state.auth_panel, "auth")
            self.assertEqual(fake_st.session_state.auth_modal_mode, "register")
            self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, fake_st.session_state)

            auth_modal.switch_profile_panel("change_password")
            self.assertEqual(fake_st.session_state.auth_panel, "change_password")
            self.assertNotIn("auth-change-name-input", fake_st.session_state)
            self.assertNotIn("pending_email_change_id", fake_st.session_state)

            auth_modal.handle_profile_modal_close()
            self.assertEqual(fake_st.session_state.auth_panel, "profile")

            fake_st.session_state.auth_redirect_on_close = "Estatisticas"
            auth_modal.close_auth_modal()
            self.assertIsNone(fake_st.session_state.auth_panel)
            set_page.assert_called_once_with("Estatisticas")

    def test_render_modal_feedback_outputs_success_error_and_info(self):
        fake_st = _FakeStreamlit()

        with patch.object(auth_modal, "st", fake_st):
            for kind, expected_class in [
                ("success", "auth-global-success"),
                ("error", "auth-global-error"),
                ("info", "auth-info-message"),
            ]:
                auth_modal.set_modal_feedback(fake_st.session_state, "<segredo>", kind)
                auth_modal._render_modal_feedback()
                self.assertIn(expected_class, fake_st.markdowns[-1][0])
                self.assertIn("&lt;segredo&gt;", fake_st.markdowns[-1][0])

    def test_google_oauth_action_renders_link_or_safe_unavailable_message(self):
        fake_st = _FakeStreamlit()
        available_service = SimpleNamespace(
            is_available=lambda: True,
            build_authorization_url=lambda state: f"https://accounts.google.com/o/oauth2/v2/auth?state={state}",
        )

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=available_service),
            patch.object(auth_modal, "store_oauth_state", return_value="state-1"),
        ):
            auth_modal._render_google_oauth_action(fake_st, key="google")

        self.assertEqual(len(fake_st.link_buttons), 1)
        self.assertIn("accounts.google.com", fake_st.link_buttons[0][1])

        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("google")
        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None):
            auth_modal._render_google_oauth_action(fake_st, key="google")

        self.assertIn(auth_modal.GOOGLE_SIGN_IN_UNAVAILABLE_MESSAGE, fake_st.markdowns[-1][0])

    def test_login_panel_validation_error_clears_processing(self):
        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("auth-login-submit")

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_login_panel()

        self.assertTrue(fake_st.rerun_called)
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")
        self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, fake_st.session_state)

    def test_signup_panel_success_routes_to_email_confirmation(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.inputs.update(
            {
                "Nome": "Ana",
                "E-mail": "ana@example.com",
                "Senha": "SenhaSegura123",
                "Confirmar senha": "SenhaSegura123",
            }
        )
        pending_service = SimpleNamespace(
            email_service=SimpleNamespace(config=SimpleNamespace(enabled=True, provider="smtp")),
            start_registration=lambda *args: SimpleNamespace(
                success=True,
                status="pending_registration_created",
                message="ok",
                email="ana@example.com",
                pending_registration_id=22,
            ),
        )
        reactivation_service = SimpleNamespace(
            email_service=SimpleNamespace(config=SimpleNamespace(enabled=True, provider="smtp"))
        )

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
            patch.object(auth_modal, "_get_pending_registration_service_or_none", return_value=pending_service),
            patch.object(auth_modal, "_get_account_reactivation_service_or_none", return_value=reactivation_service),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_signup_panel()

        self.assertEqual(fake_st.session_state.auth_panel, "confirm_email")
        self.assertEqual(fake_st.session_state.registration_flow_kind, "pending_registration")
        self.assertEqual(fake_st.session_state.pending_registration_id, 22)

    def test_confirm_email_panel_routes_reactivation_result_to_login(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state.update(
            {
                "registration_flow_kind": "reactivation",
                "account_reactivation_token_id": 5,
                "account_reactivation_email": "ana@example.com",
            }
        )
        fake_st.inputs["auth-registration-code-input"] = "123456"
        reactivation_service = SimpleNamespace(
            confirm_reactivation_code=lambda *args: SimpleNamespace(
                success=True,
                status="reactivated",
                message="ok",
                user={"id": 1, "email": "ana@example.com"},
            )
        )

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_pending_registration_service_or_none", return_value=SimpleNamespace()),
            patch.object(auth_modal, "_get_account_reactivation_service_or_none", return_value=reactivation_service),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_confirm_email_panel()

        self.assertEqual(fake_st.session_state.auth_panel, "auth")
        self.assertEqual(fake_st.session_state.auth_modal_mode, "login")
        self.assertIn(auth_modal.CONFIRM_EMAIL_REACTIVATION_SUCCESS_MESSAGE, fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY])

    def test_forgot_and_reset_password_panels_show_inline_feedback(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.inputs["auth-reset-request-email-input"] = "ana@example.com"
        reset_service = SimpleNamespace(request_password_reset=lambda email: SimpleNamespace(message="Mensagem neutra."))

        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_password_reset_service_or_none", return_value=reset_service):
            with self.assertRaises(RuntimeError):
                auth_modal._render_forgot_password_panel()

        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "info")
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Mensagem neutra.")

        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["password_reset_token"] = "raw-token"
        fake_st.inputs["auth-reset-new-password-input"] = "SenhaNova123"
        fake_st.inputs["auth-reset-confirm-password-input"] = "SenhaNova123"
        reset_service = SimpleNamespace(
            reset_password_with_token=lambda *args: SimpleNamespace(success=True, message="Senha redefinida.")
        )
        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_password_reset_service_or_none", return_value=reset_service):
            with self.assertRaises(RuntimeError):
                auth_modal._render_reset_password_panel()

        self.assertEqual(fake_st.session_state.auth_panel, "auth")
        self.assertEqual(fake_st.session_state.auth_modal_mode, "login")
        self.assertNotIn("password_reset_token", fake_st.session_state)
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Senha redefinida.")

    def test_profile_panel_renders_status_and_action_cards(self):
        fake_st = _FakeStreamlit()
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        verification_service = SimpleNamespace(is_email_verified=lambda user_id: False)

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_email_verification_service_or_none", return_value=verification_service),
        ):
            auth_modal._render_profile_panel()

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn("Meu perfil", rendered)
        self.assertIn("E-mail nao verificado", rendered)
        self.assertTrue(any(label == "Alterar senha" for label, _ in fake_st.buttons))

    def test_registration_decision_variants_are_safe_and_structured(self):
        cases = [
            (
                SimpleNamespace(success=False, status="active_email_exists", email="ana@example.com"),
                "email_instructions_available",
                "neutral",
            ),
            (
                SimpleNamespace(success=False, status="deactivated_user_found", email="ana@example.com"),
                "email_instructions_available",
                "neutral",
            ),
            (
                SimpleNamespace(success=False, status="window_expired", email="ana@example.com"),
                "email_instructions_available",
                "neutral",
            ),
            (
                SimpleNamespace(success=False, status="email_not_sent", send_result=SimpleNamespace(error_code="smtp_failed")),
                "email_sending_failed",
                None,
            ),
            (
                SimpleNamespace(success=False, status="unexpected_status"),
                "unexpected_error",
                None,
            ),
        ]

        for result, expected_status, expected_flow in cases:
            with self.subTest(expected_status=expected_status, expected_flow=expected_flow):
                step = auth_modal.resolve_registration_next_step(result, "ana@example.com")
                self.assertEqual(step.status, expected_status)
                self.assertEqual(step.flow_kind, expected_flow)
                self.assertNotIn("desativada", step.message.casefold())

    def test_handle_register_submit_reactivation_and_failure_variants(self):
        enabled_email = SimpleNamespace(config=SimpleNamespace(enabled=True, provider="smtp"))

        pending_service = SimpleNamespace(
            email_service=enabled_email,
            start_registration=lambda *args: SimpleNamespace(success=False, status="deactivated_user_found"),
        )
        reactivation_service = SimpleNamespace(
            email_service=enabled_email,
            request_reactivation=lambda email: SimpleNamespace(
                success=True,
                status="reactivation_token_created",
                email=email,
                reactivation_token_id=44,
            ),
        )
        session_state = _FakeSessionState()
        step = auth_modal.handle_register_submit(
            session_state,
            pending_service,
            reactivation_service,
            nome="Ana",
            email="ana@example.com",
            senha="SenhaSegura123",
            confirmar_senha="SenhaSegura123",
        )

        self.assertEqual(step.flow_kind, "reactivation")
        self.assertEqual(session_state["registration_flow_kind"], "reactivation")
        self.assertEqual(session_state["account_reactivation_token_id"], 44)

        reactivation_service = SimpleNamespace(
            email_service=enabled_email,
            request_reactivation=lambda email: SimpleNamespace(
                success=False,
                status="email_not_sent",
                email=email,
                send_result=SimpleNamespace(error_code="email_disabled", mode="fake"),
            ),
        )
        step = auth_modal.handle_register_submit(
            _FakeSessionState(),
            pending_service,
            reactivation_service,
            nome="Ana",
            email="ana@example.com",
            senha="SenhaSegura123",
            confirmar_senha="SenhaSegura123",
        )
        self.assertEqual(step.status, "email_sending_disabled")

        broken_pending = SimpleNamespace(email_service=enabled_email, start_registration=lambda *args: (_ for _ in ()).throw(RuntimeError("db")))
        step = auth_modal.handle_register_submit(
            _FakeSessionState(),
            broken_pending,
            SimpleNamespace(email_service=enabled_email),
            nome="Ana",
            email="ana@example.com",
            senha="SenhaSegura123",
            confirmar_senha="SenhaSegura123",
        )
        self.assertTrue(step.generic_error)

    def test_email_code_confirmation_pending_failures_are_safe(self):
        session_state = _FakeSessionState(
            {
                "registration_flow_kind": "pending_registration",
                "pending_registration_id": 10,
                "pending_registration_email": "ana@example.com",
            }
        )
        pending_service = SimpleNamespace(
            confirm_registration_code=lambda *args: SimpleNamespace(
                success=False,
                status="invalid_code",
                message="Codigo invalido.",
                user=None,
            )
        )

        result = auth_modal.handle_email_code_confirmation(
            session_state,
            pending_service,
            SimpleNamespace(),
            code="123456",
        )

        self.assertFalse(result.success)
        self.assertEqual(result.status, "invalid_code")

        pending_service = SimpleNamespace(confirm_registration_code=lambda *args: (_ for _ in ()).throw(RuntimeError("db")))
        result = auth_modal.handle_email_code_confirmation(
            session_state,
            pending_service,
            SimpleNamespace(),
            code="123456",
        )
        self.assertTrue(result.generic_error)
        self.assertEqual(result.message, auth_modal.AUTH_UNAVAILABLE_MESSAGE)

    def test_change_name_panel_updates_session_user(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        fake_st.inputs["auth-change-name-input"] = "Ana Maria"
        updated_user = {"id": 1, "nome": "Ana Maria", "email": "ana@example.com"}
        service = SimpleNamespace(update_name=lambda user_id, nome: updated_user)

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_auth_service_or_none", return_value=service),
            patch.object(auth_modal, "login_session") as login_session,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_change_name_panel()

        login_session.assert_called_once_with(fake_st.session_state, updated_user)
        self.assertEqual(fake_st.session_state.auth_panel, "profile")
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Nome atualizado com sucesso.")

    def test_change_password_panel_success_and_validation_error(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        fake_st.inputs.update(
            {
                "auth-current-password-input": "SenhaAtual123",
                "auth-new-password-input": "SenhaNova123",
                "auth-confirm-password-input": "SenhaNova123",
            }
        )
        service = SimpleNamespace(change_password=MagicMock())

        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_auth_service_or_none", return_value=service):
            with self.assertRaises(RuntimeError):
                auth_modal._render_change_password_panel()

        service.change_password.assert_called_once()
        self.assertEqual(fake_st.session_state.auth_panel, "profile")
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Senha alterada com sucesso.")

        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        fake_st.inputs.update(
            {
                "auth-current-password-input": "",
                "auth-new-password-input": "curta",
                "auth-confirm-password-input": "diferente",
            }
        )
        with patch.object(auth_modal, "st", fake_st):
            with self.assertRaises(RuntimeError):
                auth_modal._render_change_password_panel()

        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")
        self.assertIn("senha atual", fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY])

    def test_change_email_and_confirmation_panels_keep_email_pending_until_code(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        fake_st.inputs["auth-change-email-input"] = "nova@example.com"
        fake_st.inputs["auth-change-email-password-input"] = "SenhaAtual123"
        service = SimpleNamespace(
            request_email_change=lambda *args: SimpleNamespace(
                success=True,
                pending_change_id=30,
                user_id=1,
                new_email="nova@example.com",
                message="Codigo enviado.",
            )
        )

        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_email_change_service_or_none", return_value=service):
            with self.assertRaises(RuntimeError):
                auth_modal._render_change_email_panel()

        self.assertEqual(fake_st.session_state.auth_panel, "confirm_email_change")
        self.assertEqual(fake_st.session_state.pending_email_change_new_email, "nova@example.com")
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Codigo enviado.")

        fake_st.form_submitted = True
        fake_st.inputs["auth-email-change-code-input"] = "123456"
        updated_user = {"id": 1, "nome": "Ana", "email": "nova@example.com"}
        service = SimpleNamespace(
            confirm_email_change_code=lambda *args: SimpleNamespace(
                success=True,
                user=updated_user,
                message="E-mail alterado com sucesso.",
            )
        )
        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_email_change_service_or_none", return_value=service),
            patch.object(auth_modal, "login_session") as login_session,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_confirm_email_change_panel()

        login_session.assert_called_once_with(fake_st.session_state, updated_user)
        self.assertEqual(fake_st.session_state.auth_panel, "profile")
        self.assertNotIn("pending_email_change_id", fake_st.session_state)

    def test_deactivate_panel_requires_email_and_then_logs_out(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        fake_st.inputs["auth-deactivate-email-input"] = "ana@example.com"
        service = SimpleNamespace(soft_delete_user=MagicMock())

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_auth_service_or_none", return_value=service),
            patch.object(auth_modal, "logout_session") as logout_session,
            patch.object(auth_modal, "set_current_page") as set_page,
            patch.object(auth_modal, "queue_toast") as queue_toast,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_deactivate_account_panel()

        service.soft_delete_user.assert_called_once_with(1)
        logout_session.assert_called_once_with(fake_st.session_state)
        set_page.assert_called_once_with(auth_modal.DEFAULT_PAGE)
        queue_toast.assert_called_once_with(fake_st.session_state, "Conta desativada com sucesso.")

    def test_small_render_helpers_and_processing_context(self):
        fake_st = _FakeStreamlit()

        with patch.object(auth_modal, "st", fake_st):
            self.assertEqual(auth_modal._escape_text("<tag>"), "&lt;tag&gt;")
            auth_modal._render_auth_modal_style()
            auth_modal._render_auth_dialog_subtitle("Subtitulo")
            auth_modal._render_auth_dialog_heading("Titulo", "<seguro>")
            auth_modal._render_global_error(fake_st, "Erro")
            auth_modal._render_global_info(fake_st, "Info")
            auth_modal._render_field_error(fake_st, "Campo obrigatorio")
            auth_modal._render_field_errors({"email": fake_st}, {"email": "E-mail invalido", "senha": "ignorado"})

            auth_modal._start_modal_processing("Processando...")
            self.assertTrue(auth_modal._is_modal_processing())
            self.assertTrue(auth_modal._is_modal_processing("Processando..."))
            self.assertEqual(auth_modal._processing_label("Entrar", "Processando..."), "Processando...")
            self.assertTrue(auth_modal._should_process(False, "Processando..."))
            self.assertEqual(auth_modal._first_error_message({}, "fallback"), "fallback")
            with auth_modal.modal_action_processing("Salvando..."):
                self.assertTrue(auth_modal._is_modal_processing("Salvando..."))
            self.assertFalse(auth_modal._is_modal_processing())

        rendered = "\n".join(body for body, _ in fake_st.markdowns)
        self.assertIn(auth_modal.AUTH_MODAL_CSS[:20], rendered)
        self.assertIn("&lt;seguro&gt;", rendered)

    def test_service_or_none_helpers_fail_safely(self):
        helper_pairs = [
            ("_get_auth_service", auth_modal._get_auth_service_or_none),
            ("_get_email_verification_service", auth_modal._get_email_verification_service_or_none),
            ("_get_email_change_service", auth_modal._get_email_change_service_or_none),
            ("_get_password_reset_service", auth_modal._get_password_reset_service_or_none),
            ("_get_pending_registration_service", auth_modal._get_pending_registration_service_or_none),
            ("_get_account_reactivation_service", auth_modal._get_account_reactivation_service_or_none),
            ("_get_google_oauth_service", auth_modal._get_google_oauth_service_or_none),
        ]

        for target, helper in helper_pairs:
            with self.subTest(target=target):
                with patch.object(auth_modal, target, side_effect=RuntimeError("db")):
                    self.assertIsNone(helper())

    def test_render_auth_panel_dispatches_known_panels(self):
        fake_st = _FakeStreamlit()
        dispatch = {
            "auth": "_render_auth_dialog",
            "profile": "_render_profile_dialog",
            "change_name": "_render_change_name_dialog",
            "change_password": "_render_change_password_dialog",
            "change_email": "_render_change_email_dialog",
            "confirm_email_change": "_render_confirm_email_change_dialog",
            "forgot_password": "_render_forgot_password_dialog",
            "confirm_email": "_render_confirm_registration_dialog",
            "confirm_reactivation": "_render_confirm_reactivation_dialog",
            "reset_password": "_render_reset_password_dialog",
            "deactivate_account": "_render_deactivate_account_dialog",
        }

        for panel, function_name in dispatch.items():
            with self.subTest(panel=panel):
                fake_st.session_state.clear()
                fake_st.session_state.auth_panel = panel
                with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, function_name) as renderer:
                    auth_modal.render_auth_panel()
                renderer.assert_called_once()

        fake_st.session_state.clear()
        with patch.object(auth_modal, "st", fake_st):
            auth_modal.render_auth_panel()
        self.assertEqual(fake_st.markdowns[-1][0], auth_modal.AUTH_MODAL_CSS)

    def test_dialog_wrappers_call_their_panels(self):
        wrappers = [
            ("_render_profile_dialog", "_render_profile_panel"),
            ("_render_change_name_dialog", "_render_change_name_panel"),
            ("_render_change_password_dialog", "_render_change_password_panel"),
            ("_render_change_email_dialog", "_render_change_email_panel"),
            ("_render_confirm_email_change_dialog", "_render_confirm_email_change_panel"),
            ("_render_forgot_password_dialog", "_render_forgot_password_panel"),
            ("_render_confirm_registration_dialog", "_render_confirm_registration_panel"),
            ("_render_confirm_reactivation_dialog", "_render_confirm_reactivation_panel"),
            ("_render_reset_password_dialog", "_render_reset_password_panel"),
            ("_render_deactivate_account_dialog", "_render_deactivate_account_panel"),
        ]

        for wrapper_name, panel_name in wrappers:
            with self.subTest(wrapper_name=wrapper_name):
                with patch.object(auth_modal, panel_name) as panel:
                    getattr(auth_modal, wrapper_name).__wrapped__()
                panel.assert_called_once()

        with patch.object(auth_modal, "_render_signup_panel") as signup:
            fake_st = _FakeStreamlit()
            fake_st.session_state.auth_modal_mode = "register"
            with patch.object(auth_modal, "st", fake_st):
                auth_modal._render_auth_dialog.__wrapped__()
        signup.assert_called_once()

        with patch.object(auth_modal, "_render_login_panel") as login:
            fake_st = _FakeStreamlit()
            fake_st.session_state.auth_modal_mode = "login"
            with patch.object(auth_modal, "st", fake_st):
                auth_modal._render_auth_dialog.__wrapped__()
        login.assert_called_once()

    def test_login_panel_success_and_auth_validation_paths_clear_processing(self):
        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("auth-login-submit")
        fake_st.inputs["E-mail"] = "ana@example.com"
        fake_st.inputs["Senha"] = "SenhaSegura123"
        service = SimpleNamespace(authenticate=lambda email, senha: {"id": 1, "email": email, "nome": "Ana"})

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
            patch.object(auth_modal, "_get_auth_service_or_none", return_value=service),
            patch.object(auth_modal, "login_session") as login_session,
            patch.object(auth_modal, "_finish_auth_success") as finish_success,
            patch.object(auth_modal, "queue_toast") as queue_toast,
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_login_panel()

        login_session.assert_called_once()
        finish_success.assert_called_once()
        queue_toast.assert_called_once()
        self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, fake_st.session_state)

        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("auth-login-submit")
        fake_st.inputs["E-mail"] = "ana@example.com"
        fake_st.inputs["Senha"] = "errada"
        service = SimpleNamespace(authenticate=lambda email, senha: (_ for _ in ()).throw(auth_modal.AuthValidationError("E-mail ou senha invalidos.")))
        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
            patch.object(auth_modal, "_get_auth_service_or_none", return_value=service),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_login_panel()

        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "E-mail ou senha invalidos.")
        self.assertNotIn(auth_modal.AUTH_MODAL_PROCESSING_KEY, fake_st.session_state)

    def test_signup_panel_validation_and_service_unavailable_paths(self):
        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.inputs.update({"Nome": "", "E-mail": "invalido", "Senha": "curta", "Confirmar senha": "outra"})

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_signup_panel()
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")

        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.inputs.update(
            {
                "Nome": "Ana",
                "E-mail": "ana@example.com",
                "Senha": "SenhaSegura123",
                "Confirmar senha": "SenhaSegura123",
            }
        )
        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_google_oauth_service_or_none", return_value=None),
            patch.object(auth_modal, "_get_pending_registration_service_or_none", return_value=None),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_signup_panel()
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], auth_modal.AUTH_UNAVAILABLE_MESSAGE)

    def test_profile_resend_verification_success_and_missing_service(self):
        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("auth-profile-resend-verification")
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        verification_service = SimpleNamespace(
            is_email_verified=lambda user_id: False,
            resend_verification_email=lambda user_id: SimpleNamespace(message="Verificacao reenviada."),
        )

        with (
            patch.object(auth_modal, "st", fake_st),
            patch.object(auth_modal, "_get_email_verification_service_or_none", return_value=verification_service),
        ):
            with self.assertRaises(RuntimeError):
                auth_modal._render_profile_panel()

        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Verificacao reenviada.")

        fake_st = _FakeStreamlit()
        fake_st.clicked_keys.add("auth-profile-resend-verification")
        fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
        with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_email_verification_service_or_none", return_value=None):
            with self.assertRaises(RuntimeError):
                auth_modal._render_profile_panel()
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KIND_KEY], "error")

    def test_profile_panels_without_user_route_to_login(self):
        panels = [
            auth_modal._render_profile_panel,
            auth_modal._render_change_name_panel,
            auth_modal._render_change_password_panel,
            auth_modal._render_change_email_panel,
            auth_modal._render_confirm_email_change_panel,
            auth_modal._render_deactivate_account_panel,
        ]

        for panel in panels:
            fake_st = _FakeStreamlit()
            with self.subTest(panel=panel.__name__):
                with patch.object(auth_modal, "st", fake_st):
                    panel()
                self.assertEqual(fake_st.session_state.auth_panel, "auth")
                self.assertEqual(fake_st.session_state.auth_modal_mode, "login")

    def test_change_email_panel_safe_failure_statuses(self):
        for status, expected_message in [
            ("duplicate_email", auth_modal.EMAIL_CHANGE_DUPLICATE_MESSAGE),
            ("email_disabled", auth_modal.EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE),
            ("send_failed", auth_modal.EMAIL_CHANGE_SEND_FAILED_MESSAGE),
            ("other", "Mensagem segura."),
        ]:
            fake_st = _FakeStreamlit()
            fake_st.form_submitted = True
            fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
            fake_st.inputs["auth-change-email-input"] = "nova@example.com"
            fake_st.inputs["auth-change-email-password-input"] = "SenhaAtual123"
            service = SimpleNamespace(
                request_email_change=lambda *args, status=status: SimpleNamespace(
                    success=False,
                    status=status,
                    message="Mensagem segura.",
                )
            )
            with self.subTest(status=status):
                with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_email_change_service_or_none", return_value=service):
                    with self.assertRaises(RuntimeError):
                        auth_modal._render_change_email_panel()
                self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], expected_message)

    def test_confirm_email_change_panel_empty_expired_and_invalid_paths(self):
        for status, expected_message in [
            ("invalid_code", auth_modal.EMAIL_CHANGE_INVALID_CODE_MESSAGE),
            ("expired", auth_modal.EMAIL_CHANGE_EXPIRED_CODE_MESSAGE),
            ("used", "Codigo usado."),
        ]:
            fake_st = _FakeStreamlit()
            fake_st.form_submitted = True
            fake_st.session_state.update(
                {
                    "auth_user": {"id": 1, "nome": "Ana", "email": "ana@example.com"},
                    "pending_email_change_id": 30,
                    "pending_email_change_user_id": 1,
                    "pending_email_change_new_email": "nova@example.com",
                }
            )
            fake_st.inputs["auth-email-change-code-input"] = "123456"
            service = SimpleNamespace(
                confirm_email_change_code=lambda *args, status=status: SimpleNamespace(
                    success=False,
                    status=status,
                    message="Codigo usado.",
                )
            )
            with self.subTest(status=status):
                with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_email_change_service_or_none", return_value=service):
                    with self.assertRaises(RuntimeError):
                        auth_modal._render_confirm_email_change_panel()
                self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], expected_message)

        fake_st = _FakeStreamlit()
        fake_st.form_submitted = True
        fake_st.session_state.update(
            {
                "auth_user": {"id": 1, "nome": "Ana", "email": "ana@example.com"},
                "pending_email_change_id": 30,
                "pending_email_change_user_id": 1,
                "pending_email_change_new_email": "nova@example.com",
            }
        )
        fake_st.inputs["auth-email-change-code-input"] = ""
        with patch.object(auth_modal, "st", fake_st):
            with self.assertRaises(RuntimeError):
                auth_modal._render_confirm_email_change_panel()
        self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], "Informe o codigo enviado por e-mail.")

    def test_deactivate_panel_mismatch_and_service_unavailable_paths(self):
        for typed_email, service, expected_message in [
            ("outra@example.com", SimpleNamespace(), "Digite seu e-mail para confirmar a desativacao."),
            ("ana@example.com", None, auth_modal.AUTH_UNAVAILABLE_MESSAGE),
        ]:
            fake_st = _FakeStreamlit()
            fake_st.form_submitted = True
            fake_st.session_state["auth_user"] = {"id": 1, "nome": "Ana", "email": "ana@example.com"}
            fake_st.inputs["auth-deactivate-email-input"] = typed_email
            with self.subTest(typed_email=typed_email):
                with patch.object(auth_modal, "st", fake_st), patch.object(auth_modal, "_get_auth_service_or_none", return_value=service):
                    with self.assertRaises(RuntimeError):
                        auth_modal._render_deactivate_account_panel()
                self.assertEqual(fake_st.session_state[auth_modal.AUTH_MODAL_FEEDBACK_KEY], expected_message)


if __name__ == "__main__":
    unittest.main()
