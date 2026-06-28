from pathlib import Path
import unittest

APP_PATH = Path("app_ai_chat.py")
AUTH_MODAL_PATH = Path("src/ui/auth_modal.py")
HEADER_PATH = Path("src/ui/header.py")
SIDEBAR_PATH = Path("src/ui/sidebar.py")
STATISTICS_PATH = Path("src/ui/statistics_page.py")
PROTECTED_CHAT_PATH = Path("src/ui/protected_chat.py")


class TestAppAiChat(unittest.TestCase):
    def test_app_existe(self):
        self.assertTrue(APP_PATH.exists())

    def test_app_carrega_ia_apenas_no_processamento_do_chat(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertNotRegex(source, r"(?m)^from src\.ai\.datasus_ai import perguntar_datasus$")
        self.assertNotRegex(source, r"(?m)^import pandas\b")
        self.assertIn("def _get_datasus_question_runner", source)
        self.assertIn("def _get_pandas_module", source)
        self.assertIn("@st.cache_resource(show_spinner=False)", source)
        self.assertIn("perguntar_datasus = _get_datasus_question_runner()", source)
        self.assertIn("resposta = perguntar_datasus(prompt)", source)

    def test_app_valida_autenticacao_antes_do_chat(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.auth.session import can_access_chat", source)
        self.assertIn("if not can_access_chat(st.session_state):", source)
        self.assertIn("st.session_state.pending_prompt = None", source)
        self.assertIn("open_auth_modal(", source)
        self.assertIn("Tentativa bloqueada de chat sem usuario autenticado", source)

    def test_chat_respeita_verificacao_de_email_quando_exigida(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")

        self.assertIn("is_email_verification_required", app_source)
        self.assertIn("def _can_use_chat_with_email_verification", app_source)
        self.assertIn("_get_email_verification_service().is_email_verified", app_source)
        self.assertIn("render_chat_email_verification_gate", app_source)
        self.assertIn("Tentativa bloqueada de chat com e-mail nao verificado.", app_source)
        self.assertIn("EMAIL_VERIFICATION_REQUIRED_MESSAGE", protected_source)
        self.assertIn("E-mail pendente de verificacao", protected_source)
        self.assertIn('st.button("Abrir meu perfil"', protected_source)

    def test_app_trata_link_de_recuperacao_de_senha(self):
        app_source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("def _handle_password_reset_query_param", app_source)
        self.assertIn('st.query_params.get("reset_password_token")', app_source)
        self.assertIn("st.session_state.password_reset_token = clean_token", app_source)
        self.assertIn('set_auth_panel("reset_password", redirect_on_close=DEFAULT_PAGE)', app_source)
        self.assertIn('del st.query_params["reset_password_token"]', app_source)
        self.assertIn("_handle_password_reset_query_param()", app_source)

    def test_app_nao_usa_link_para_alteracao_de_email(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertNotIn("confirm_email_change_token", app_source + auth_source)
        self.assertNotIn("def _handle_email_change_query_param", app_source)
        self.assertIn("def _render_confirm_email_change_panel", auth_source)
        self.assertIn("service.confirm_email_change_code(", auth_source)
        self.assertIn('"confirm_email_change"', auth_source)
        self.assertIn("pending_email_change_id", auth_source)
        self.assertIn("auth-email-change-code-input", auth_source)
        self.assertIn("Confirmar novo e-mail", auth_source)

    def test_app_trata_link_de_verificacao_de_email(self):
        app_source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("def _handle_email_verification_query_param", app_source)
        self.assertIn('st.query_params.get("verify_email_token")', app_source)
        self.assertIn("_get_email_verification_service().verify_email_token(clean_token)", app_source)
        self.assertIn("email_verification_feedback", app_source)
        self.assertIn('del st.query_params["verify_email_token"]', app_source)
        self.assertIn("_handle_email_verification_query_param()", app_source)
        self.assertIn("def _render_email_verification_feedback", app_source)
        self.assertIn("st.success(message)", app_source)
        self.assertIn("st.error(message)", app_source)

    def test_chat_tem_fluxo_confiavel_de_mensagens_e_erros(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("_UNSAFE_RESPONSE_PATTERNS", source)
        self.assertIn("Resposta tecnica da IA substituida por mensagem amigavel.", source)
        self.assertIn("return GENERIC_ERROR_MESSAGE", source)
        self.assertIn('logger.warning(\n            "Erro seguro app_ai_chat | operacao=processar_prompt', source)
        self.assertIn('if st.session_state.get("pending_prompt") == clean_prompt:', source)
        self.assertIn('st.session_state.pending_prompt = clean_prompt', source)
        self.assertIn('_render_chat_history(show_processing=True)', source)
        self.assertIn('_render_input_form(disabled=True)', source)
        self.assertIn('st.session_state.messages.append({"role": "user", "content": prompt})', source)
        self.assertIn('st.session_state.messages.append({"role": "assistant", "content": resposta})', source)
        self.assertIn("if submitted and prompt:", source)

        clear_index = source.index("st.session_state.pending_prompt = None", source.index("def _process_pending_prompt"))
        user_append_index = source.index('st.session_state.messages.append({"role": "user", "content": prompt})')
        loading_index = source.index("_render_chat_history(show_processing=True)")
        disabled_input_index = source.index("_render_input_form(disabled=True)")
        assistant_append_index = source.index('st.session_state.messages.append({"role": "assistant", "content": resposta})')

        self.assertLess(clear_index, user_append_index)
        self.assertLess(user_append_index, loading_index)
        self.assertLess(loading_index, disabled_input_index)
        self.assertLess(disabled_input_index, assistant_append_index)

    def test_chat_persiste_historico_para_usuario_autenticado(self):
        source = APP_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.chat.chat_history_service import ChatHistoryService", source)
        self.assertIn("def _get_chat_history_service", source)
        self.assertIn("def _persist_chat_history_message", source)
        self.assertIn("st.session_state.chat_history_session_id = session.id", source)
        self.assertIn('_persist_chat_history_message(\n            user_id=user_id,\n            role="user"', source)
        self.assertIn('_persist_chat_history_message(\n            user_id=user_id,\n            role="assistant"', source)
        self.assertIn('assistant_status = "error"', source)
        self.assertIn("Erro seguro historico_chat", source)

    def test_estatisticas_permanece_publica_e_chat_fica_protegido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        statistics_source = STATISTICS_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")

        self.assertIn("if current_page == CHAT_PAGE:", app_source)
        self.assertIn("_render_chat_page()", app_source)
        self.assertIn("else:\n        render_statistics_page()", app_source)
        self.assertNotIn("can_access_chat", statistics_source)
        self.assertIn("sem login", statistics_source)
        self.assertIn("open_auth_modal(", protected_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", protected_source)

    def test_app_contem_referencias_visuais_esperadas(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [APP_PATH, SIDEBAR_PATH, STATISTICS_PATH]
        )

        expected_texts = [
            "Assistente Estatístico SIA/DATASUS",
            "Chat IA",
            "Estatísticas",
            "Painel de Estatísticas",
            "Ver painel de estatÃ­sticas",
            "O painel serÃ¡ aberto em uma nova aba.",
            "app.powerbi.com/view",
            "images",
            "logo.png",
            "brand-logo",
            "Digite uma pergunta estatística",
        ]

        expected_texts = [
            text
            for text in expected_texts
            if not text.startswith(("Ver painel de estat", "O painel ser"))
        ] + ["Ver painel de estat", "O painel ser"]

        for text in expected_texts:
            self.assertIn(text, source)

    def test_sidebar_usa_logo_real_e_hero_nao_tem_grafico_decorativo(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")
        statistics_source = STATISTICS_PATH.read_text(encoding="utf-8")

        self.assertIn("LOGO_PATH", sidebar_source)
        self.assertIn("_get_sidebar_logo_data_uri", sidebar_source)
        self.assertIn("images", sidebar_source)
        self.assertIn("logo.png", sidebar_source)
        self.assertIn('<img class="brand-logo"', sidebar_source)
        self.assertIn(".brand-logo", app_source)
        self.assertNotIn("brand-spark", app_source + sidebar_source)
        self.assertNotIn("hero-chart", app_source + statistics_source)

    def test_app_usa_sidebar_como_navegacao_unica(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.ui.sidebar import", app_source)
        self.assertIn("def render_sidebar", sidebar_source)
        self.assertIn('st.button("Estatísticas"', sidebar_source)
        self.assertIn('st.button("Chat IA"', sidebar_source)
        self.assertIn("sidebar-click-targets", app_source + sidebar_source)
        self.assertIn(".st-key-sidebar-nav-estatisticas", app_source)
        self.assertIn(".st-key-sidebar-nav-chat-ia", app_source)
        self.assertIn("position: fixed", app_source)
        self.assertIn("color: transparent", app_source)
        self.assertNotIn('href="?page=', sidebar_source)
        self.assertIn('"estatisticas": DEFAULT_PAGE', sidebar_source)
        self.assertIn('"chat-ia": CHAT_PAGE', sidebar_source)
        self.assertNotIn("st.radio(", app_source + sidebar_source)
        self.assertNotIn("nav-tabs", app_source + sidebar_source)

        removed_pages = [
            "Visão Geral",
            "Análise Mensal",
            "Análise Anual",
            "Demografia",
        ]

        for page in removed_pages:
            self.assertNotIn(page, app_source + sidebar_source)

    def test_app_usa_dialog_para_fluxos_de_autenticacao(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("render_auth_panel", app_source)
        self.assertIn('@st.dialog("Acesso ao Chat IA"', auth_source)
        self.assertIn('@st.dialog("Meu perfil"', auth_source)
        self.assertIn('on_dismiss=_clear_auth_panel', auth_source)
        self.assertIn("auth_modal_mode", auth_source)
        self.assertIn("def open_auth_modal", auth_source)
        self.assertIn("def switch_auth_modal_mode", auth_source)
        self.assertIn("def close_auth_modal", auth_source)
        self.assertIn("if mode in {\"signup\", \"register\"}", auth_source)
        self.assertIn("auth-dialog-subtitle", auth_source)
        self.assertNotIn("auth-card-heading", auth_source)
        self.assertNotIn("auth-profile-card", auth_source)

    def test_modal_auth_nao_reseta_cadastro_no_chat_protegido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        header_source = HEADER_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.ui.auth_modal import close_auth_modal, open_auth_modal, render_auth_panel, set_auth_panel", app_source)
        self.assertIn("and not st.session_state.get(\"auth_panel\")", app_source)
        self.assertIn("open_auth_modal(", app_source)
        self.assertIn("open_auth_modal(", header_source)
        self.assertIn("open_auth_modal(", protected_source)
        self.assertIn('mode="register"', protected_source)
        self.assertIn("switch_auth_modal_mode(switch_mode)", auth_source)
        self.assertIn('switch_mode="register"', auth_source)
        self.assertIn('switch_mode="login"', auth_source)

    def test_modal_auth_redireciona_cancelamento_do_chat_para_estatisticas(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        protected_source = PROTECTED_CHAT_PATH.read_text(encoding="utf-8")
        sidebar_source = SIDEBAR_PATH.read_text(encoding="utf-8")

        self.assertIn("auth_redirect_on_close", app_source)
        self.assertIn("auth_target_page_on_success", app_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", app_source)
        self.assertIn("target_page_on_success=CHAT_PAGE", app_source)
        self.assertIn("redirect_on_close=DEFAULT_PAGE", protected_source)
        self.assertIn("target_page_on_success=CHAT_PAGE", protected_source)
        self.assertIn("def close_auth_panel", auth_source)
        self.assertIn("set_current_page(str(redirect_page))", auth_source)
        self.assertIn("def _finish_auth_success", auth_source)
        self.assertIn("set_current_page(str(target_page))", auth_source)
        self.assertIn("def set_current_page", sidebar_source)
        self.assertIn('st.query_params["page"]', sidebar_source)

    def test_modal_auth_tem_backdrop_suave_e_card_claro(self):
        source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("AUTH_MODAL_CSS", source)
        self.assertIn("def _render_auth_modal_style", source)
        self.assertIn('[data-testid="stDialog"]::backdrop', source)
        self.assertIn("rgba(15, 23, 42, 0.18)", source)
        self.assertIn("background: rgba(15, 23, 42, 0.14)", source)
        self.assertIn("backdrop-filter: blur(4px)", source)
        self.assertIn("backdrop-filter: blur(5px)", source)
        self.assertIn("max-width: 28rem", source)
        self.assertIn("background: #FFFFFF !important", source)
        self.assertIn("color: #0F172A !important", source)
        self.assertIn('[data-testid="InputInstructions"]', source)
        self.assertIn("color: #FFFFFF !important", source)
        self.assertIn("border-radius: 0.875rem", source)
        self.assertIn("input:focus", source)
        self.assertIn("box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16)", source)
        self.assertIn("display: none !important", source)
        self.assertIn('[data-testid="stTextInput"]:has(input[type="password"]) button', source)
        self.assertIn("visibility: hidden !important", source)
        self.assertIn("pointer-events: none !important", source)

    def test_inputs_e_acoes_do_modal_tem_estilo_polido(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn('[data-testid="stTextInput"] input', app_source)
        self.assertNotIn("::-ms-reveal", app_source + auth_source)
        self.assertIn("input:focus-visible", app_source)
        self.assertIn("border-radius: 0.875rem", app_source)
        self.assertIn("box-shadow: 0 0 0 3px rgba(123, 44, 191, 0.16)", app_source)
        self.assertIn("validate_login_fields", auth_source)
        self.assertIn("validate_register_fields", auth_source)
        self.assertIn("auth-global-error", auth_source)
        self.assertIn("auth-global-success", auth_source)
        self.assertIn("auth-field-error", auth_source)
        self.assertIn("auth-info-message", auth_source)
        self.assertIn('role="alert"', auth_source)
        self.assertIn('role="status"', auth_source)
        self.assertIn("#991B1B", auth_source)
        self.assertIn("#B42318", auth_source)
        self.assertIn("AUTH_MODAL_FEEDBACK_KEY", auth_source)
        self.assertIn("AUTH_MODAL_PROCESSING_KEY", auth_source)
        self.assertIn("def set_modal_feedback", auth_source)
        self.assertIn("def _clear_modal_feedback", auth_source)
        self.assertIn("def _start_modal_processing", auth_source)
        self.assertIn("def _is_modal_processing", auth_source)
        self.assertIn("def _processing_label", auth_source)
        self.assertIn("def _should_process", auth_source)
        self.assertIn("def modal_action_processing", auth_source)
        self.assertIn("def _render_modal_feedback", auth_source)
        self.assertIn("_render_modal_feedback()", auth_source)
        self.assertIn("st.session_state[AUTH_MODAL_PROCESSING_KEY] = message", auth_source)
        self.assertIn("st.session_state.pop(AUTH_MODAL_PROCESSING_KEY, None)", auth_source)
        self.assertIn("on_click=_start_modal_processing", auth_source)
        self.assertIn("disabled=is_processing", auth_source)
        self.assertIn("_processing_label(", auth_source)
        self.assertIn("_should_process(submitted", auth_source)
        self.assertIn("with st.spinner(message):", auth_source)
        self.assertIn("finally:", auth_source)
        self.assertIn("_render_global_error(global_error_slot, AUTH_UNAVAILABLE_MESSAGE)", auth_source)
        self.assertIn("_render_field_errors(field_error_slots, field_errors)", auth_source)
        self.assertIn("Não foi possível acessar a autenticação agora.", auth_source)
        self.assertIn("auth-login-submit", auth_source)
        self.assertIn('.st-key-auth-login-submit [data-testid="stButton"] button', auth_source)
        self.assertIn("background: linear-gradient(135deg, #7B2CBF 0%, #2563EB 100%)", auth_source)
        self.assertIn("Entrando...", auth_source)
        self.assertIn("Enviando codigo...", auth_source)
        self.assertIn("Verificando codigo...", auth_source)
        self.assertIn("Enviando instrucoes...", auth_source)
        self.assertIn("Redefinindo senha...", auth_source)
        self.assertIn("Salvando...", auth_source)
        self.assertIn("Alterando senha...", auth_source)
        self.assertIn("Desativando...", auth_source)
        self.assertIn("auth-login-forgot-password", auth_source)
        self.assertIn("auth-login-google-action", auth_source)
        self.assertIn("auth-signup-google-action", auth_source)
        self.assertIn("Entrar com Google", auth_source)
        self.assertIn("Criar conta com Google", auth_source)
        self.assertIn("GOOGLE_SIGN_IN_UNAVAILABLE_MESSAGE", auth_source)
        self.assertIn("GoogleOAuthService", auth_source)
        self.assertIn("store_oauth_state(st.session_state)", auth_source)
        self.assertIn("service.build_authorization_url(state)", auth_source)
        self.assertIn("st.link_button(label, auth_url", auth_source)
        self.assertNotIn("Google OAuth sera implementado em fase futura.", auth_source)
        self.assertIn("auth-login-divider", auth_source)
        self.assertIn("auth-password-reset-request-form", auth_source)
        self.assertIn("auth-password-reset-confirm-form", auth_source)
        self.assertIn("PASSWORD_RESET_NEUTRAL_MESSAGE", auth_source)
        self.assertIn("service.request_password_reset(email)", auth_source)
        self.assertIn("service.reset_password_with_token(reset_token, nova_senha, confirmar_senha)", auth_source)
        self.assertIn("password_reset_token", auth_source)
        self.assertIn('@st.dialog("Redefinir senha"', auth_source)
        self.assertIn("PendingRegistrationService", auth_source)
        self.assertIn("AccountReactivationService", auth_source)
        self.assertIn("service.start_registration(nome, email, senha, confirmar_senha)", auth_source)
        self.assertIn("pending_registration_id", auth_source)
        self.assertIn("def handle_email_code_confirmation", auth_source)
        self.assertIn("pending_registration_service.confirm_registration_code", auth_source)
        self.assertIn("account_reactivation_service.confirm_reactivation_code", auth_source)
        self.assertIn("handle_email_code_confirmation(", auth_source)
        self.assertNotIn("Solicitacao de cadastro nao encontrada", auth_source)
        self.assertIn('@st.dialog("Confirmar e-mail"', auth_source)
        self.assertIn("REGISTRATION_PUBLIC_NEUTRAL_MESSAGE", auth_source)
        self.assertIn("REGISTRATION_PUBLIC_EMAIL_UNAVAILABLE_MESSAGE", auth_source)
        self.assertIn("def resolve_registration_next_step", auth_source)
        self.assertIn('"email_instructions_available"', auth_source)
        self.assertIn("next_step = resolve_registration_next_step(result, email)", auth_source)
        self.assertIn("registration_flow_kind", auth_source)
        self.assertIn('set_auth_panel("confirm_email")', auth_source)
        self.assertIn("Se for possivel continuar com este e-mail, enviaremos instrucoes para ele.", auth_source)
        self.assertNotIn("Encontramos uma conta desativada associada a este e-mail.", auth_source)
        self.assertNotIn("auth-reactivation-send-code", auth_source)
        self.assertNotIn("Enviar codigo de reativacao", auth_source)
        self.assertNotIn("reactivation_offer", auth_source)
        self.assertIn("service.request_reactivation(email)", auth_source)
        self.assertIn("account_reactivation_token_id", auth_source)
        self.assertIn("Codigo invalido ou expirado.", auth_source)
        self.assertIn("Codigo invalido ou expirado. Inicie o processo novamente.", auth_source)
        self.assertNotIn('@st.dialog("Reativar conta"', auth_source)
        self.assertNotIn("user = service.create_user(nome, email, senha, confirmar_senha)", auth_source)
        self.assertIn("def _render_auth_footer", auth_source)
        self.assertIn('switch_key="auth-login-go-signup"', auth_source)
        self.assertIn('switch_key="auth-signup-go-login"', auth_source)
        self.assertIn('switch_mode="register"', auth_source)
        self.assertIn('switch_mode="login"', auth_source)
        self.assertIn("auth-dialog-footer", auth_source)
        self.assertIn(".st-key-auth-login-go-signup", auth_source)
        self.assertIn(".st-key-auth-signup-go-login", auth_source)
        self.assertIn("border: 1px solid rgba(123, 44, 191, 0.42)", auth_source)
        self.assertIn("height: 2.85rem", auth_source)
        self.assertNotIn("prompt_text=", auth_source)
        self.assertNotIn("Não tem conta?", auth_source)
        self.assertNotIn("Já tem conta?", auth_source)
        self.assertIn('action_label="Criar conta"', auth_source)
        self.assertIn('action_label="Entrar"', auth_source)
        self.assertIn("Acesso ao Chat IA", auth_source)
        self.assertIn("Entre para continuar usando o chat inteligente.", auth_source)
        self.assertIn("Preencha seus dados para acessar o Chat IA.", auth_source)
        self.assertNotIn("auth-dialog-cancel", auth_source)
        self.assertNotIn('st.button("Cancelar"', auth_source)
        self.assertNotIn('st.button("Fechar", key="auth-login-close"', auth_source)
        self.assertNotIn('st.button("Fechar", key="auth-signup-close"', auth_source)

    def test_app_trata_callback_google_oauth(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("from src.auth.google_oauth_service import", app_source)
        self.assertIn("def _handle_google_oauth_query_param", app_source)
        self.assertIn('_get_query_param_value("code")', app_source)
        self.assertIn('_get_query_param_value("state")', app_source)
        self.assertIn("validate_oauth_state(st.session_state, state)", app_source)
        self.assertIn("_get_google_oauth_service().exchange_code_for_identity(code)", app_source)
        self.assertIn("_get_auth_user_service().authenticate_google_identity(", app_source)
        self.assertIn("login_session(st.session_state, user)", app_source)
        self.assertIn("close_auth_modal(redirect=False)", app_source)
        self.assertIn("clear_oauth_state(st.session_state)", app_source)
        self.assertIn('del st.query_params[key]', app_source)
        self.assertIn("_handle_google_oauth_query_param()", app_source)
        self.assertIn("def _render_google_oauth_feedback", app_source)
        self.assertIn("GOOGLE_OAUTH_TARGET_PAGE_KEY", app_source + auth_source)

    def test_profile_menu_e_modal_tem_fluxo_enxuto(self):
        app_source = APP_PATH.read_text(encoding="utf-8")
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")
        header_source = HEADER_PATH.read_text(encoding="utf-8")

        self.assertIn('st.button("Meu perfil"', header_source)
        self.assertIn('st.button("Sair"', header_source)
        self.assertIn("queue_toast(st.session_state, \"Sessão encerrada.\")", header_source)
        self.assertNotIn('key="auth-menu-name"', header_source)
        self.assertNotIn('key="auth-menu-password"', header_source)
        self.assertNotIn('key="auth-menu-email"', header_source)
        self.assertIn("def _render_profile_action_card", auth_source)
        self.assertIn("auth-profile-action-card", auth_source)
        self.assertIn("auth-profile-action-title", auth_source)
        self.assertIn("auth-profile-action-description", auth_source)
        self.assertIn(".auth-profile-action-card:hover", auth_source)
        self.assertIn('title="Alterar nome"', auth_source)
        self.assertIn('description="Atualize o nome exibido na sua conta."', auth_source)
        self.assertIn('button_key="auth-profile-change-name"', auth_source)
        self.assertIn('target_panel="change_name"', auth_source)
        self.assertIn('title="Alterar e-mail"', auth_source)
        self.assertIn('description="Atualize o e-mail usado para acessar sua conta."', auth_source)
        self.assertIn('button_key="auth-profile-change-email"', auth_source)
        self.assertIn('target_panel="change_email"', auth_source)
        self.assertIn('title="Alterar senha"', auth_source)
        self.assertIn('description="Troque sua senha de acesso com seguranca."', auth_source)
        self.assertIn('button_key="auth-profile-change-password"', auth_source)
        self.assertIn('target_panel="change_password"', auth_source)
        self.assertIn("action_columns = st.columns(3, gap=\"small\")", auth_source)
        self.assertIn("Zona de seguranca", auth_source)
        self.assertIn("Desativar conta", auth_source)
        self.assertIn("auth-profile-deactivate", auth_source)
        self.assertIn("auth-deactivate-account-form", auth_source)
        self.assertIn("service.soft_delete_user(int(user[\"id\"]))", auth_source)
        self.assertIn("logout_session(st.session_state)", auth_source)
        self.assertIn("set_current_page(DEFAULT_PAGE)", auth_source)
        self.assertIn("queue_toast(st.session_state, \"Conta desativada com sucesso.\")", auth_source)
        self.assertIn("PROFILE_SUBPANELS", auth_source)
        self.assertIn("def handle_profile_modal_close", auth_source)
        self.assertIn('st.session_state.get("auth_panel") in PROFILE_SUBPANELS', auth_source)
        self.assertIn('set_auth_panel("profile")', auth_source)
        self.assertIn("close_auth_modal(redirect=False)", auth_source)
        self.assertIn("_clear_modal_feedback(st.session_state)", auth_source)
        self.assertIn('@st.dialog("Meu perfil", width="large", on_dismiss=handle_profile_modal_close)', auth_source)
        self.assertIn('@st.dialog("Alterar nome", width="large", on_dismiss=handle_profile_modal_close)', auth_source)
        self.assertIn('@st.dialog("Alterar senha", width="large", on_dismiss=handle_profile_modal_close)', auth_source)
        self.assertIn('@st.dialog("Alterar e-mail", width="large", on_dismiss=handle_profile_modal_close)', auth_source)
        self.assertIn('@st.dialog("Desativar conta", width="large", on_dismiss=handle_profile_modal_close)', auth_source)
        self.assertIn("auth-profile-actions", auth_source)
        self.assertIn("auth-profile-info-card", auth_source)
        self.assertIn("auth-profile-info-grid", auth_source)
        self.assertNotIn('<span class="auth-profile-field-label">Perfil</span>', auth_source)
        self.assertIn("Status do e-mail", auth_source)
        self.assertIn("E-mail verificado", auth_source)
        self.assertIn("E-mail nao verificado", auth_source)
        self.assertIn("auth-profile-resend-verification", auth_source)
        self.assertIn("verification_service.resend_verification_email(int(user[\"id\"]))", auth_source)
        self.assertIn("Gerenciar conta", auth_source)
        self.assertIn("O e-mail da conta so sera alterado depois que voce informar o codigo enviado ao novo endereco.", auth_source)
        self.assertIn("auth-change-email-password-input", auth_source)
        self.assertIn("service.request_email_change(int(user[\"id\"]), clean_email, senha_atual)", auth_source)
        self.assertIn("EMAIL_CHANGE_DUPLICATE_MESSAGE", auth_source)
        self.assertIn("EMAIL_CHANGE_EMAIL_DISABLED_MESSAGE", auth_source)
        self.assertIn("EMAIL_CHANGE_SEND_FAILED_MESSAGE", auth_source)
        self.assertIn("pending_email_change_id", auth_source)
        self.assertIn('set_auth_panel("confirm_email_change")', auth_source)
        self.assertNotIn("service.update_email(int(user[\"id\"]), clean_email)", auth_source)
        self.assertIn('set_modal_feedback(st.session_state, "Nome atualizado com sucesso.")', auth_source)
        self.assertIn('set_modal_feedback(st.session_state, "Senha alterada com sucesso.")', auth_source)
        self.assertIn("auth-profile-form-panel auth-password-form-panel", auth_source)
        self.assertIn(':has(.auth-password-form-panel) [data-testid="stForm"]', auth_source)
        self.assertIn(':has(.auth-password-form-panel) input[type="password"]', auth_source)
        self.assertIn(".st-key-auth-password-back", auth_source)
        self.assertIn("justify-content: center !important", auth_source)
        self.assertIn("border-radius: 999px", auth_source)
        self.assertIn(
            'st.button("Voltar ao perfil", key="auth-password-back", use_container_width=False',
            auth_source,
        )
        self.assertIn("disabled=is_processing", auth_source)
        self.assertIn('@st.dialog("Meu perfil", width="large"', auth_source)
        self.assertIn(".st-key-auth-menu-logout button", app_source)
        self.assertIn("#FEF2F2", app_source)
        self.assertIn("#B42318", app_source)
        self.assertIn('[data-testid="stTextInput"] button', auth_source)
        self.assertIn('[data-testid="stTextInput"]:has(input[type="password"]) button', auth_source)
        self.assertIn("background: rgba(123, 44, 191, 0.08)", auth_source)

    def test_profile_actions_separam_troca_de_painel_do_submit(self):
        auth_source = AUTH_MODAL_PATH.read_text(encoding="utf-8")

        self.assertIn("PROFILE_WIDGET_KEYS", auth_source)
        self.assertIn("def _clear_profile_form_state", auth_source)
        self.assertIn("def switch_profile_panel", auth_source)
        self.assertIn("switch_profile_panel(target_panel)", auth_source)
        self.assertIn("st.session_state.pop(key, None)", auth_source)

        for key in [
            "auth-change-name-input",
            "auth-change-email-input",
            "auth-change-email-password-input",
            "auth-email-change-code-input",
            "auth-current-password-input",
            "auth-new-password-input",
            "auth-confirm-password-input",
            "auth-deactivate-email-input",
        ]:
            self.assertIn(key, auth_source)

        for function_name in [
            "_render_change_name_panel",
            "_render_change_email_panel",
            "_render_change_password_panel",
            "_render_deactivate_account_panel",
        ]:
            start = auth_source.index(f"def {function_name}")
            next_def = auth_source.find("\ndef ", start + 1)
            panel_source = auth_source[start:next_def if next_def != -1 else len(auth_source)]
            submit_index = panel_source.index("if _should_process(submitted")
            if function_name == "_render_change_email_panel":
                service_index = panel_source.index("service = _get_email_change_service_or_none()")
            else:
                service_index = panel_source.index("service = _get_auth_service_or_none()")

        self.assertGreater(service_index, submit_index)

        self.assertIn("Informe o novo nome.", auth_source)
        self.assertIn("Informe sua senha atual.", auth_source)
        self.assertIn("Informe um e-mail diferente do atual.", auth_source)
        self.assertIn("EMAIL_CHANGE_DUPLICATE_MESSAGE", auth_source)

    def test_app_ui_foi_separada_em_componentes(self):
        source = APP_PATH.read_text(encoding="utf-8")

        expected_imports = [
            "from src.ui.auth_modal import close_auth_modal, open_auth_modal, render_auth_panel, set_auth_panel",
            "from src.ui.header import render_auth_header",
            "from src.ui.protected_chat import render_chat_auth_gate",
            "from src.ui.sidebar import CHAT_PAGE, DEFAULT_PAGE, get_current_page, render_sidebar, set_current_page",
            "from src.ui.statistics_page import render_statistics_page",
        ]

        for import_line in expected_imports:
            self.assertIn(import_line, source)

        self.assertNotIn("def render_auth_header", source)
        self.assertNotIn("def render_sidebar", source)
        self.assertNotIn("def render_auth_panel", source)

    def test_app_nao_chama_etl_principal(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        )

        for name in ["extract_data", "transform_datasus", "load_data_sus", "main.py"]:
            self.assertNotIn(name, source)

    def test_app_nao_importa_pandasai_ou_banco_diretamente(self):
        source = APP_PATH.read_text(encoding="utf-8")

        forbidden_fragments = [
            "pandasai",
            "psycopg2",
            "sqlalchemy",
            "read_only_datasus",
            "data_provider",
        ]

        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)

    def test_app_nao_contem_comandos_sql_de_escrita(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        ).upper()

        for command in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE"]:
            self.assertNotRegex(source, rf"\b{command}\b")

    def test_app_nao_contem_to_sql(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in [
                APP_PATH,
                AUTH_MODAL_PATH,
                HEADER_PATH,
                SIDEBAR_PATH,
                STATISTICS_PATH,
                PROTECTED_CHAT_PATH,
            ]
        )

        self.assertNotIn("DataFrame.to_sql", source)
        self.assertNotIn(".to_sql", source)
        self.assertNotIn("to_sql(", source)


if __name__ == "__main__":
    unittest.main()
